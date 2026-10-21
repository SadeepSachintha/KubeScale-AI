package middleware

import (
	"context"
	"net/http"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"golang.org/x/time/rate"
)

// clientVisitor stores a rate limiter and its last seen timestamp.
type clientVisitor struct {
	limiter  *rate.Limiter
	lastSeen time.Time
}

// IPRateLimiter manages per-client token bucket limiters.
type IPRateLimiter struct {
	mu       sync.RWMutex
	visitors map[string]*clientVisitor
	rate     rate.Limit
	burst    int
}

// NewIPRateLimiter constructs a token bucket rate limiter with cleanup lifecycle.
func NewIPRateLimiter(ctx context.Context, r rate.Limit, burst int, cleanupInterval time.Duration) *IPRateLimiter {
	limiter := &IPRateLimiter{
		visitors: make(map[string]*clientVisitor),
		rate:     r,
		burst:    burst,
	}

	// Background sweeper to prune stale visitor entries and prevent unbounded memory growth
	go func() {
		ticker := time.NewTicker(cleanupInterval)
		defer ticker.Stop()

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				limiter.cleanup(cleanupInterval * 2)
			}
		}
	}()

	return limiter
}

// getVisitor retrieves or instantiates a token bucket for a given client identifier.
func (i *IPRateLimiter) getVisitor(ip string) *rate.Limiter {
	i.mu.Lock()
	defer i.mu.Unlock()

	v, exists := i.visitors[ip]
	if !exists {
		lim := rate.NewLimiter(i.rate, i.burst)
		i.visitors[ip] = &clientVisitor{
			limiter:  lim,
			lastSeen: time.Now(),
		}
		return lim
	}

	v.lastSeen = time.Now()
	return v.limiter
}

// cleanup removes clients that have been idle longer than maxAge.
func (i *IPRateLimiter) cleanup(maxAge time.Duration) {
	i.mu.Lock()
	defer i.mu.Unlock()

	now := time.Now()
	for ip, v := range i.visitors {
		if now.Sub(v.lastSeen) > maxAge {
			delete(i.visitors, ip)
		}
	}
}

// RateLimitMiddleware enforces token-bucket rate limiting per client IP.
func RateLimitMiddleware(limiter *IPRateLimiter) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Bypass health check and metrics endpoints
		path := c.Request.URL.Path
		if path == "/healthz" || path == "/readyz" || path == "/metrics" {
			c.Next()
			return
		}

		clientIP := c.ClientIP()
		vLimiter := limiter.getVisitor(clientIP)

		if !vLimiter.Allow() {
			c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
				"error":     "rate limit exceeded: too many requests to inference gateway",
				"code":      http.StatusTooManyRequests,
				"timestamp": time.Now().UTC().Format(time.RFC3339),
			})
			return
		}

		c.Next()
	}
}
