package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestTelemetryIngestValidation(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// In test mode, Kafka broker list can be dummy since we test validation and queuing
	th := NewTelemetryHandler([]string{"127.0.0.1:9092"}, "telemetry-raw", 100, 1)
	defer th.Close()

	router := gin.New()
	router.POST("/api/v1/telemetry", th.IngestTelemetry)

	// Test 1: Valid payload
	validPayload := map[string]interface{}{
		"device_id":  "edge-device-01",
		"timestamp":  time.Now().UnixMilli(),
		"event_type": "inference_latency",
		"model_name": "sentiment_onnx",
		"latency_ms": 12.4,
		"metrics": map[string]float64{
			"throughput_rps": 350.0,
		},
	}
	body, _ := json.Marshal(validPayload)

	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/api/v1/telemetry", bytes.NewReader(body))
	req1.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w1, req1)

	if w1.Code != http.StatusAccepted {
		t.Fatalf("expected status 202 Accepted, got %d. Body: %s", w1.Code, w1.Body.String())
	}

	// Test 2: Missing required fields
	invalidPayload := map[string]interface{}{
		"model_name": "sentiment_onnx",
	}
	badBody, _ := json.Marshal(invalidPayload)

	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/api/v1/telemetry", bytes.NewReader(badBody))
	req2.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w2, req2)

	if w2.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400 Bad Request, got %d", w2.Code)
	}

	// Test 3: Malformed JSON
	w3 := httptest.NewRecorder()
	req3, _ := http.NewRequest(http.MethodPost, "/api/v1/telemetry", bytes.NewReader([]byte("invalid json")))
	req3.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w3, req3)

	if w3.Code != http.StatusBadRequest {
		t.Fatalf("expected status 400 Bad Request on malformed JSON, got %d", w3.Code)
	}
}
