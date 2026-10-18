# ==============================================================================
# Multi-Stage Production Dockerfile for KubeScale AI FastAPI Gateway
# ==============================================================================

# Stage 1: Build stage for dependency compilation
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Final minimal runtime container
FROM python:3.11-slim AS runner

WORKDIR /app

# Create a non-root system user and group for security
RUN groupadd -g 10001 kubescale && \
    useradd -u 10001 -g kubescale -s /bin/bash -m appuser

# Copy installed Python packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local

# Ensure path includes user-installed binaries
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Copy application source code
COPY --chown=appuser:kubescale ./app /app/app

# Switch to non-privileged user
USER 10001

# Expose HTTP port for Kubernetes Service & Ingress
EXPOSE 8000

# Container-level health check probe
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Start Uvicorn ASGI server with production defaults
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--access-log"]
