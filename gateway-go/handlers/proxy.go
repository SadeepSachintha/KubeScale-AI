package handlers

import (
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"time"

	"github.com/gin-gonic/gin"
)

// ProxyHandler encapsulates reverse proxy routing to Triton and vLLM runtimes.
type ProxyHandler struct {
	targetURL *url.URL
	proxy     *httputil.ReverseProxy
	transport *http.Transport
}

// NewProxyHandler initializes an optimized ReverseProxy with connection pooling.
func NewProxyHandler(rawTargetURL string) (*ProxyHandler, error) {
	parsedURL, err := url.Parse(rawTargetURL)
	if err != nil {
		return nil, fmt.Errorf("invalid upstream inference URL '%s': %w", rawTargetURL, err)
	}

	// High-throughput connection pooling transport for low-latency inference calls
	transport := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: (&net.Dialer{
			Timeout:   5 * time.Second,
			KeepAlive: 30 * time.Second,
		}).DialContext,
		ForceAttemptHTTP2:     true,
		MaxIdleConns:          100,
		MaxIdleConnsPerHost:   100,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
	}

	proxy := httputil.NewSingleHostReverseProxy(parsedURL)
	proxy.Transport = transport

	// Custom Director to manage path forwarding, host rewriting, and trace headers
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)
		req.Host = parsedURL.Host

		// Ensure client IP headers are preserved
		if clientIP, _, err := net.SplitHostPort(req.RemoteAddr); err == nil {
			req.Header.Set("X-Forwarded-For", clientIP)
		}

		// Inject or forward distributed tracing header if missing
		if req.Header.Get("X-Request-ID") == "" {
			req.Header.Set("X-Request-ID", fmt.Sprintf("req-%d", time.Now().UnixNano()))
		}
	}

	// Production JSON error envelope on upstream network/connection failures
	proxy.ErrorHandler = func(w http.ResponseWriter, req *http.Request, proxyErr error) {
		log.Printf("[Proxy Error] Upstream '%s%s' failed: %v", parsedURL.Host, req.URL.Path, proxyErr)

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)

		errResponse := map[string]interface{}{
			"error":     fmt.Sprintf("downstream inference runtime unavailable: %v", proxyErr),
			"code":      http.StatusBadGateway,
			"timestamp": time.Now().UTC().Format(time.RFC3339),
			"upstream":  parsedURL.Host,
		}
		_ = json.NewEncoder(w).Encode(errResponse)
	}

	return &ProxyHandler{
		targetURL: parsedURL,
		proxy:     proxy,
		transport: transport,
	}, nil
}

// HandleTritonProxy forwards Triton V2 requests (/v2/*) directly to the inference server.
func (p *ProxyHandler) HandleTritonProxy(c *gin.Context) {
	p.proxy.ServeHTTP(c.Writer, c.Request)
}

// HandleVLLMProxy forwards vLLM / OpenAI API requests (/v1/*) to the runtime.
func (p *ProxyHandler) HandleVLLMProxy(c *gin.Context) {
	p.proxy.ServeHTTP(c.Writer, c.Request)
}

// HandleSynchronousInference routes generic /predict requests directly to default model inference.
func (p *ProxyHandler) HandleSynchronousInference(defaultModel string) gin.HandlerFunc {
	return func(c *gin.Context) {
		// If request path is /predict, rewrite to Triton V2 endpoint: /v2/models/{defaultModel}/infer
		c.Request.URL.Path = fmt.Sprintf("/v2/models/%s/infer", defaultModel)
		p.proxy.ServeHTTP(c.Writer, c.Request)
	}
}

// CheckUpstreamHealth performs a lightweight HTTP HEAD/GET probe to verify Triton connectivity.
func (p *ProxyHandler) CheckUpstreamHealth() bool {
	client := &http.Client{
		Transport: p.transport,
		Timeout:   2 * time.Second,
	}

	healthURL := fmt.Sprintf("%s://%s/v2/health/ready", p.targetURL.Scheme, p.targetURL.Host)
	resp, err := client.Get(healthURL)
	if err != nil {
		// Check live endpoint as fallback
		liveURL := fmt.Sprintf("%s://%s/v2/health/live", p.targetURL.Scheme, p.targetURL.Host)
		resp, err = client.Get(liveURL)
		if err != nil {
			return false
		}
	}
	defer resp.Body.Close()

	return resp.StatusCode == http.StatusOK
}
