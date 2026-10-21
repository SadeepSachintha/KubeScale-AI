package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

func TestRateLimitMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Rate limiter allowing 2 requests burst, 1 req/sec
	limiter := NewIPRateLimiter(ctx, rate.Limit(1), 2, 1*time.Minute)

	router := gin.New()
	router.Use(RateLimitMiddleware(limiter))
	router.GET("/test", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok"})
	})

	// Request 1: Should succeed
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodGet, "/test", nil)
	req1.RemoteAddr = "192.168.1.100:1234"
	router.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w1.Code)
	}

	// Request 2: Should succeed (burst=2)
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodGet, "/test", nil)
	req2.RemoteAddr = "192.168.1.100:1234"
	router.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d", w2.Code)
	}

	// Request 3: Should be rate-limited (429)
	w3 := httptest.NewRecorder()
	req3, _ := http.NewRequest(http.MethodGet, "/test", nil)
	req3.RemoteAddr = "192.168.1.100:1234"
	router.ServeHTTP(w3, req3)
	if w3.Code != http.StatusTooManyRequests {
		t.Fatalf("expected status 429 Too Many Requests, got %d", w3.Code)
	}
}
