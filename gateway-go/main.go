package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"

	"gateway-go/handlers"
	"gateway-go/middleware"
)

// Config encapsulates environment-driven gateway parameters.
type Config struct {
	Port                 string
	UpstreamInferenceURL string
	KafkaBrokers         []string
	KafkaTelemetryTopic  string
	DefaultModelName     string
	RateLimitRPS         float64
	RateLimitBurst       int
	Environment          string
}

func loadConfig() Config {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8000"
	}

	upstreamURL := os.Getenv("TRITON_HTTP_URL")
	if upstreamURL == "" {
		upstreamURL = os.Getenv("UPSTREAM_INFERENCE_URL")
	}
	if upstreamURL == "" {
		upstreamURL = "http://kubescale-inference:8000"
	}
	if !strings.HasPrefix(upstreamURL, "http://") && !strings.HasPrefix(upstreamURL, "https://") {
		upstreamURL = "http://" + upstreamURL
	}

	brokersEnv := os.Getenv("KAFKA_BOOTSTRAP_SERVERS")
	if brokersEnv == "" {
		brokersEnv = "kubescale-kafka-bootstrap:9092"
	}
	brokers := strings.Split(brokersEnv, ",")

	telemetryTopic := os.Getenv("KAFKA_TELEMETRY_TOPIC")
	if telemetryTopic == "" {
		telemetryTopic = "telemetry-raw"
	}

	defaultModel := os.Getenv("DEFAULT_MODEL_NAME")
	if defaultModel == "" {
		defaultModel = "sentiment_onnx"
	}

	rateRPS := 1000.0
	if rpsStr := os.Getenv("RATE_LIMIT_RPS"); rpsStr != "" {
		if r, err := strconv.ParseFloat(rpsStr, 64); err == nil && r > 0 {
			rateRPS = r
		}
	}

	rateBurst := 2000
	if burstStr := os.Getenv("RATE_LIMIT_BURST"); burstStr != "" {
		if b, err := strconv.Atoi(burstStr); err == nil && b > 0 {
			rateBurst = b
		}
	}

	env := os.Getenv("ENVIRONMENT")
	if env == "" {
		env = "dev"
	}

	return Config{
		Port:                 port,
		UpstreamInferenceURL: upstreamURL,
		KafkaBrokers:         brokers,
		KafkaTelemetryTopic:  telemetryTopic,
		DefaultModelName:     defaultModel,
		RateLimitRPS:         rateRPS,
		RateLimitBurst:       rateBurst,
		Environment:          env,
	}
}

func main() {
	cfg := loadConfig()

	log.Printf("Starting KubeScale AI Go Ingress Gateway [Env: %s, Port: %s]", cfg.Environment, cfg.Port)
	log.Printf("Configured Upstream Triton Runtime: %s", cfg.UpstreamInferenceURL)
	log.Printf("Configured Kafka Brokers: %v | Telemetry Topic: %s", cfg.KafkaBrokers, cfg.KafkaTelemetryTopic)

	// Set Gin mode
	if cfg.Environment != "dev" && cfg.Environment != "local" {
		gin.SetMode(gin.ReleaseMode)
	}

	// Root cancellation context for background workers
	rootCtx, rootCancel := context.WithCancel(context.Background())
	defer rootCancel()

	// Initialize Reverse Proxy Handler
	proxyHandler, err := handlers.NewProxyHandler(cfg.UpstreamInferenceURL)
	if err != nil {
		log.Fatalf("Fatal: failed to initialize proxy transport: %v", err)
	}

	// Initialize Kafka Async Telemetry Ingestion Handler
	telemetryHandler := handlers.NewTelemetryHandler(
		cfg.KafkaBrokers,
		cfg.KafkaTelemetryTopic,
		10000, // In-memory queue buffer
		4,     // Concurrent Kafka flush worker routines
	)

	// Initialize Token Bucket Rate Limiter
	rateLimiter := middleware.NewIPRateLimiter(
		rootCtx,
		rate.Limit(cfg.RateLimitRPS),
		cfg.RateLimitBurst,
		3*time.Minute,
	)

	// Setup Engine & Core Middlewares
	router := gin.New()
	router.Use(gin.Recovery())
	router.Use(middleware.PrometheusMiddleware())
	router.Use(middleware.RateLimitMiddleware(rateLimiter))

	// -------------------------------------------------------------------------
	// Operational & Health Probes
	// -------------------------------------------------------------------------
	router.GET("/healthz", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"status":    "UP",
			"service":   "kubescale-gateway-go",
			"runtime":   "golang",
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		})
	})

	router.GET("/readyz", func(c *gin.Context) {
		upstreamHealthy := proxyHandler.CheckUpstreamHealth()
		if !upstreamHealthy && cfg.Environment != "dev" {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"status":    "NOT_READY",
				"reason":    "upstream inference engine unreachable",
				"timestamp": time.Now().UTC().Format(time.RFC3339),
			})
			return
		}

		c.JSON(http.StatusOK, gin.H{
			"status":           "READY",
			"upstream_triton":  upstreamHealthy,
			"telemetry_stream": "ACTIVE",
			"timestamp":        time.Now().UTC().Format(time.RFC3339),
		})
	})

	router.GET("/metrics", middleware.MetricsHandler())

	// -------------------------------------------------------------------------
	// API Discovery
	// -------------------------------------------------------------------------
	router.GET("/", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"service":     "KubeScale AI Go High-Throughput Gateway",
			"version":     "2.0.0",
			"engine":      "Golang Ingress Proxy",
			"endpoints": gin.H{
				"health":    "/healthz",
				"readiness": "/readyz",
				"metrics":   "/metrics",
				"telemetry": "/api/v1/telemetry",
				"triton_v2": "/v2/*path",
				"vllm_v1":   "/v1/*path",
				"predict":   "/predict",
			},
		})
	})

	// -------------------------------------------------------------------------
	// High-Frequency Telemetry Ingestion
	// -------------------------------------------------------------------------
	router.POST("/api/v1/telemetry", telemetryHandler.IngestTelemetry)
	router.POST("/telemetry", telemetryHandler.IngestTelemetry)

	// -------------------------------------------------------------------------
	// Inference Reverse Proxy Routes (Triton & vLLM)
	// -------------------------------------------------------------------------
	router.Any("/v2/*proxyPath", proxyHandler.HandleTritonProxy)
	router.Any("/v1/*proxyPath", proxyHandler.HandleVLLMProxy)
	router.POST("/predict", proxyHandler.HandleSynchronousInference(cfg.DefaultModelName))

	// HTTP Server Configuration with Keep-Alive Timeouts
	server := &http.Server{
		Addr:              fmt.Sprintf(":%s", cfg.Port),
		Handler:           router,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       120 * time.Second,
	}

	// Non-blocking server startup
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Critical: HTTP server failed: %v", err)
		}
	}()

	log.Printf("Gateway HTTP server listening on port %s", cfg.Port)

	// -------------------------------------------------------------------------
	// Graceful Shutdown on OS Signal (SIGTERM, SIGINT)
	// -------------------------------------------------------------------------
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	sig := <-quit

	log.Printf("Received termination signal (%s). Initiating graceful shutdown...", sig)

	// 15-second grace period for in-flight requests and Kafka flushing
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer shutdownCancel()

	// Shut down HTTP server
	if err := server.Shutdown(shutdownCtx); err != nil {
		log.Printf("Warning: HTTP server shutdown error: %v", err)
	} else {
		log.Println("HTTP server closed cleanly.")
	}

	// Flush Kafka telemetry queue and close workers
	if err := telemetryHandler.Close(); err != nil {
		log.Printf("Warning: Kafka telemetry handler close error: %v", err)
	} else {
		log.Println("Kafka telemetry producer flushed and disconnected cleanly.")
	}

	rootCancel()
	log.Println("KubeScale AI Go Gateway shutdown complete.")
}
