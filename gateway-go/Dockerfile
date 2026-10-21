# ==============================================================================
# Build Stage: Multi-stage Golang 1.23 Alpine Compilation
# ==============================================================================
FROM golang:1.23-alpine AS builder

# Install SSL certificates and build tools
RUN apk add --no-cache ca-certificates git tzdata

WORKDIR /src

# Leverage Docker layer caching for dependencies
COPY go.mod go.sum ./
RUN go mod download && go mod verify

# Copy source tree
COPY . .

# Compile fully static, stripped binary with zero CGo dependency
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -a \
    -installsuffix cgo \
    -ldflags="-s -w -extldflags '-static' -X 'main.Version=2.0.0'" \
    -o /bin/gateway .

# Create non-root user and group files for scratch runtime
RUN echo "kubescale:x:10001:10001:KubeScale NonRoot User:/:/sbin/nologin" > /etc/passwd_scratch && \
    echo "kubescale:x:10001:" > /etc/group_scratch

# ==============================================================================
# Final Stage: Ultra-lightweight Static Distroless / Scratch Runtime (< 25MB)
# ==============================================================================
FROM scratch

# Copy root CA certificates, timezones, and non-root user credentials
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=builder /etc/passwd_scratch /etc/passwd
COPY --from=builder /etc/group_scratch /etc/group

# Copy compiled static gateway binary
COPY --from=builder /bin/gateway /bin/gateway

# Run as non-root user (UID 10001) for strict Kubernetes Pod Security Standards
USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["/bin/gateway"]
