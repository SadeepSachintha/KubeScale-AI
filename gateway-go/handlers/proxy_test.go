package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

// closeNotifyingRecorder wraps httptest.ResponseRecorder and satisfies http.CloseNotifier for Gin proxy tests.
type closeNotifyingRecorder struct {
	*httptest.ResponseRecorder
	closed chan bool
}

func newCloseNotifyingRecorder() *closeNotifyingRecorder {
	return &closeNotifyingRecorder{
		ResponseRecorder: httptest.NewRecorder(),
		closed:           make(chan bool, 1),
	}
}

func (c *closeNotifyingRecorder) CloseNotify() <-chan bool {
	return c.closed
}

func TestProxyHandlerForwarding(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// Mock downstream Triton server
	mockTriton := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/v2/models/sentiment_onnx/infer" {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"model_name":"sentiment_onnx","outputs":[{"name":"OUTPUT_0","data":[0.85,0.15]}]}`))
			return
		}
		if r.URL.Path == "/v2/health/ready" {
			w.WriteHeader(http.StatusOK)
			return
		}
		http.NotFound(w, r)
	}))
	defer mockTriton.Close()

	proxyHandler, err := NewProxyHandler(mockTriton.URL)
	if err != nil {
		t.Fatalf("failed to create proxy handler: %v", err)
	}

	router := gin.New()
	router.Any("/v2/*proxyPath", proxyHandler.HandleTritonProxy)
	router.POST("/predict", proxyHandler.HandleSynchronousInference("sentiment_onnx"))

	// Test 1: Direct V2 proxy request
	w1 := newCloseNotifyingRecorder()
	req1, _ := http.NewRequest(http.MethodPost, "/v2/models/sentiment_onnx/infer", nil)
	router.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w1.Code)
	}

	// Test 2: Synchronous predict endpoint rewriting
	w2 := newCloseNotifyingRecorder()
	req2, _ := http.NewRequest(http.MethodPost, "/predict", nil)
	router.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w2.Code)
	}

	// Test 3: Upstream health probe
	healthy := proxyHandler.CheckUpstreamHealth()
	if !healthy {
		t.Fatalf("expected upstream to be healthy")
	}
}

func TestProxyHandlerUpstreamFailure(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// Target invalid endpoint to simulate crashed/unreachable upstream
	proxyHandler, err := NewProxyHandler("http://127.0.0.1:59999")
	if err != nil {
		t.Fatalf("failed to create proxy handler: %v", err)
	}

	router := gin.New()
	router.Any("/v2/*proxyPath", proxyHandler.HandleTritonProxy)

	w := newCloseNotifyingRecorder()
	req, _ := http.NewRequest(http.MethodPost, "/v2/models/sentiment_onnx/infer", nil)
	router.ServeHTTP(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected status 502 Bad Gateway, got %d", w.Code)
	}

	var errBody map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &errBody); err != nil {
		t.Fatalf("expected valid JSON error envelope: %v", err)
	}
	if errBody["code"] != float64(http.StatusBadGateway) {
		t.Fatalf("expected error code 502 in JSON body")
	}
}
