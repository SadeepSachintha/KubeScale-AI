package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/segmentio/kafka-go"

	"gateway-go/middleware"
)

// EdgeTelemetryPayload represents high-frequency operational telemetry from edge devices and clients.
type EdgeTelemetryPayload struct {
	DeviceID  string                 `json:"device_id" binding:"required"`
	Timestamp int64                  `json:"timestamp" binding:"required"`
	EventType string                 `json:"event_type" binding:"required"`
	ModelName string                 `json:"model_name,omitempty"`
	BatchSize int                    `json:"batch_size,omitempty"`
	LatencyMs float64                `json:"latency_ms,omitempty"`
	Metrics   map[string]float64     `json:"metrics,omitempty"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
}

// TelemetryHandler handles validation and non-blocking asynchronous publication to Kafka.
type TelemetryHandler struct {
	writer      *kafka.Writer
	queueChan   chan kafka.Message
	topic       string
	ctx         context.Context
	cancel      context.CancelFunc
	wg          sync.WaitGroup
	payloadPool sync.Pool
}

// NewTelemetryHandler initializes Kafka async writer with high-throughput batching.
func NewTelemetryHandler(brokers []string, topic string, queueDepth int, numWorkers int) *TelemetryHandler {
	ctx, cancel := context.WithCancel(context.Background())

	writer := &kafka.Writer{
		Addr:         kafka.TCP(brokers...),
		Topic:        topic,
		Balancer:     &kafka.LeastBytes{},
		BatchSize:    200,
		BatchTimeout: 10 * time.Millisecond,
		Async:        true,
		RequiredAcks: kafka.RequireOne,
		Completion: func(messages []kafka.Message, err error) {
			if err != nil {
				log.Printf("[Kafka Producer Error] Failed to publish %d telemetry messages: %v", len(messages), err)
				for _, msg := range messages {
					middleware.TelemetryEventsTotal.WithLabelValues("kafka_error", string(msg.Key)).Inc()
				}
			}
		},
	}

	th := &TelemetryHandler{
		writer:    writer,
		queueChan: make(chan kafka.Message, queueDepth),
		topic:     topic,
		ctx:       ctx,
		cancel:    cancel,
		payloadPool: sync.Pool{
			New: func() interface{} {
				return new(EdgeTelemetryPayload)
			},
		},
	}

	// Spawn dedicated background workers to drain internal buffer into Kafka writer
	for i := 0; i < numWorkers; i++ {
		th.wg.Add(1)
		go th.workerLoop()
	}

	return th
}

// workerLoop drains the telemetry channel respecting context cancellation.
func (th *TelemetryHandler) workerLoop() {
	defer th.wg.Done()

	for {
		select {
		case <-th.ctx.Done():
			// Drain remaining messages before exiting
			for {
				select {
				case msg := <-th.queueChan:
					start := time.Now()
					_ = th.writer.WriteMessages(context.Background(), msg)
					middleware.KafkaPublishLatency.WithLabelValues(th.topic, "success").Observe(time.Since(start).Seconds())
				default:
					return
				}
			}
		case msg := <-th.queueChan:
			start := time.Now()
			err := th.writer.WriteMessages(th.ctx, msg)
			if err != nil {
				middleware.KafkaPublishLatency.WithLabelValues(th.topic, "error").Observe(time.Since(start).Seconds())
			} else {
				middleware.KafkaPublishLatency.WithLabelValues(th.topic, "success").Observe(time.Since(start).Seconds())
			}
		}
	}
}

// IngestTelemetry handles incoming POST /api/v1/telemetry with minimal memory allocations.
func (th *TelemetryHandler) IngestTelemetry(c *gin.Context) {
	// Acquire zeroed struct from pool to reduce GC pressure
	payload := th.payloadPool.Get().(*EdgeTelemetryPayload)
	*payload = EdgeTelemetryPayload{}
	defer th.payloadPool.Put(payload)

	// Stream decode JSON directly from request body
	decoder := json.NewDecoder(io.LimitReader(c.Request.Body, 1024*1024)) // 1MB payload cap
	if err := decoder.Decode(payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     fmt.Sprintf("invalid JSON payload: %v", err),
			"code":      http.StatusBadRequest,
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		})
		middleware.TelemetryEventsTotal.WithLabelValues("bad_request", "unknown").Inc()
		return
	}

	// Basic validation
	if payload.DeviceID == "" || payload.EventType == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"error":     "missing required fields: 'device_id' and 'event_type' are mandatory",
			"code":      http.StatusBadRequest,
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		})
		middleware.TelemetryEventsTotal.WithLabelValues("validation_error", payload.EventType).Inc()
		return
	}

	if payload.Timestamp == 0 {
		payload.Timestamp = time.Now().UnixMilli()
	}

	// Serialize to wire bytes for Kafka message
	dataBytes, err := json.Marshal(payload)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error":     "failed to serialize message payload",
			"code":      http.StatusInternalServerError,
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		})
		return
	}

	msg := kafka.Message{
		Key:   []byte(payload.DeviceID),
		Value: dataBytes,
		Time:  time.Now(),
		Headers: []kafka.Header{
			{Key: "event_type", Value: []byte(payload.EventType)},
			{Key: "model_name", Value: []byte(payload.ModelName)},
		},
	}

	// Non-blocking channel send with backpressure handling
	select {
	case th.queueChan <- msg:
		middleware.TelemetryEventsTotal.WithLabelValues("accepted", payload.EventType).Inc()
		c.JSON(http.StatusAccepted, gin.H{
			"status":     "accepted",
			"device_id":  payload.DeviceID,
			"event_type": payload.EventType,
			"timestamp":  time.Now().UTC().Format(time.RFC3339),
		})
	default:
		// Queue full - backpressure shed
		middleware.TelemetryEventsTotal.WithLabelValues("dropped_backpressure", payload.EventType).Inc()
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error":     "telemetry ingest buffer saturated (backpressure shed)",
			"code":      http.StatusServiceUnavailable,
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		})
	}
}

// Close gracefully terminates workers and flushes in-flight Kafka messages.
func (th *TelemetryHandler) Close() error {
	th.cancel()
	th.wg.Wait()
	return th.writer.Close()
}
