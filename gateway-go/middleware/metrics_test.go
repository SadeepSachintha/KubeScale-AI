package middleware

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestMetricsEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	router.Use(PrometheusMiddleware())
	router.GET("/sample", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})
	router.GET("/metrics", MetricsHandler())

	// Generate sample traffic to trigger metric increments
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodGet, "/sample", nil)
	router.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w1.Code)
	}

	// Scrape /metrics endpoint
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodGet, "/metrics", nil)
	router.ServeHTTP(w2, req2)

	if w2.Code != http.StatusOK {
		t.Fatalf("expected status 200 on /metrics, got %d", w2.Code)
	}

	body := w2.Body.String()
	if !strings.Contains(body, "kubescale_gateway_http_requests_total") {
		t.Errorf("expected metric kubescale_gateway_http_requests_total in output")
	}
	if !strings.Contains(body, "kubescale_gateway_request_duration_seconds") {
		t.Errorf("expected metric kubescale_gateway_request_duration_seconds in output")
	}
}
