package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"gateway-go/handlers"
	"gateway-go/middleware"
)

func TestMainRouterEndpoints(t *testing.T) {
	gin.SetMode(gin.TestMode)

	// Mock upstream Triton
	mockTriton := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ready"}`))
	}))
	defer mockTriton.Close()

	proxyHandler, err := handlers.NewProxyHandler(mockTriton.URL)
	if err != nil {
		t.Fatalf("failed to init proxy: %v", err)
	}

	rootCtx, rootCancel := context.WithCancel(context.Background())
	defer rootCancel()

	rateLimiter := middleware.NewIPRateLimiter(rootCtx, rate.Limit(100), 200, time.Minute)

	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(middleware.PrometheusMiddleware())
	router.Use(middleware.RateLimitMiddleware(rateLimiter))

	router.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":  "UP",
			"service": "kubescale-gateway-go",
			"runtime": "golang",
		})
	})

	router.GET("/readyz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":          "READY",
			"upstream_triton": proxyHandler.CheckUpstreamHealth(),
		})
	})

	router.GET("/", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"service": "KubeScale AI Go High-Throughput Gateway",
			"version": "2.0.0",
		})
	})

	// Test 1: Health probe
	w1 := httptest.NewRecorder()
	req1, _ := http.NewRequest(http.MethodGet, "/healthz", nil)
	router.ServeHTTP(w1, req1)
	if w1.Code != http.StatusOK {
		t.Fatalf("expected 200 on /healthz, got %d", w1.Code)
	}
	var healthBody map[string]interface{}
	_ = json.Unmarshal(w1.Body.Bytes(), &healthBody)
	if healthBody["status"] != "UP" {
		t.Fatalf("expected status UP, got %v", healthBody["status"])
	}

	// Test 2: Readiness probe
	w2 := httptest.NewRecorder()
	req2, _ := http.NewRequest(http.MethodGet, "/readyz", nil)
	router.ServeHTTP(w2, req2)
	if w2.Code != http.StatusOK {
		t.Fatalf("expected 200 on /readyz, got %d", w2.Code)
	}

	// Test 3: Root discovery
	w3 := httptest.NewRecorder()
	req3, _ := http.NewRequest(http.MethodGet, "/", nil)
	router.ServeHTTP(w3, req3)
	if w3.Code != http.StatusOK {
		t.Fatalf("expected 200 on /, got %d", w3.Code)
	}
}
