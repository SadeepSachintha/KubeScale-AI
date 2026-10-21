package middleware

import (
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	metricsOnce sync.Once

	// HTTPRequestsTotal counts all completed HTTP requests partitioned by method, path, and HTTP status.
	HTTPRequestsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "kubescale",
			Subsystem: "gateway",
			Name:      "http_requests_total",
			Help:      "Total number of HTTP requests processed by KubeScale Gateway.",
		},
		[]string{"method", "path", "status"},
	)

	// HTTPRequestDuration tracks request latency distributions in seconds.
	HTTPRequestDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: "kubescale",
			Subsystem: "gateway",
			Name:      "request_duration_seconds",
			Help:      "Histogram of HTTP request latencies in seconds.",
			Buckets:   []float64{0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0},
		},
		[]string{"method", "path", "status"},
	)

	// HTTPActiveConnections tracks currently in-flight requests.
	HTTPActiveConnections = prometheus.NewGauge(
		prometheus.GaugeOpts{
			Namespace: "kubescale",
			Subsystem: "gateway",
			Name:      "active_connections",
			Help:      "Current number of active in-flight HTTP connections.",
		},
	)

	// TelemetryEventsTotal tracks edge telemetry ingest results.
	TelemetryEventsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Namespace: "kubescale",
			Subsystem: "gateway",
			Name:      "telemetry_events_total",
			Help:      "Total edge telemetry payloads ingested partitioned by status.",
		},
		[]string{"status", "event_type"},
	)

	// KafkaPublishLatency tracks Kafka produce latency.
	KafkaPublishLatency = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: "kubescale",
			Subsystem: "gateway",
			Name:      "kafka_publish_duration_seconds",
			Help:      "Duration of Kafka produce operations in seconds.",
			Buckets:   []float64{0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5},
		},
		[]string{"topic", "status"},
	)
)

// InitMetrics registers all custom Prometheus metrics idempotently.
func InitMetrics() {
	metricsOnce.Do(func() {
		prometheus.MustRegister(
			HTTPRequestsTotal,
			HTTPRequestDuration,
			HTTPActiveConnections,
			TelemetryEventsTotal,
			KafkaPublishLatency,
		)
	})
}

// PrometheusMiddleware observes incoming requests and exports metrics.
func PrometheusMiddleware() gin.HandlerFunc {
	InitMetrics()

	return func(c *gin.Context) {
		// Ignore /metrics and probe paths from latency bloating
		path := c.FullPath()
		if path == "" {
			path = c.Request.URL.Path
		}
		if path == "/metrics" || path == "/healthz" || path == "/readyz" {
			c.Next()
			return
		}

		HTTPActiveConnections.Inc()
		defer HTTPActiveConnections.Dec()

		start := time.Now()
		c.Next()
		duration := time.Since(start).Seconds()

		statusStr := strconv.Itoa(c.Writer.Status())
		method := c.Request.Method

		HTTPRequestsTotal.WithLabelValues(method, path, statusStr).Inc()
		HTTPRequestDuration.WithLabelValues(method, path, statusStr).Observe(duration)
	}
}

// MetricsHandler provides an HTTP handler for Prometheus scraping.
func MetricsHandler() gin.HandlerFunc {
	h := promhttp.Handler()
	return func(c *gin.Context) {
		h.ServeHTTP(c.Writer, c.Request)
	}
}
