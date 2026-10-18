#!/usr/bin/env bash
# ==============================================================================
# Setup OpenTelemetry Distributed Tracing (Jaeger All-In-One / OTLP Collector)
# ==============================================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-kubescale}"
RELEASE_NAME="${RELEASE_NAME:-kubescale}"

echo "======================================================================"
echo "  Deploying OpenTelemetry & Jaeger Tracing Stack"
echo "  Namespace: ${NAMESPACE}"
echo "======================================================================"

# Verify kubectl access
if ! command -v kubectl &> /dev/null; then
    echo "[ERROR] 'kubectl' is not installed or not in PATH."
    exit 1
fi

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

echo ">>> Applying Jaeger & OTLP Collector manifest via Helm..."
if command -v helm &> /dev/null; then
    helm upgrade --install "${RELEASE_NAME}" ./helm/kubescale \
        --namespace "${NAMESPACE}" \
        --set tracing.enabled=true \
        --set tracing.jaeger.enabled=true
else
    echo "[INFO] Helm not detected. Applying Jaeger manifest directly..."
    kubectl apply -n "${NAMESPACE}" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: kubescale-jaeger
  labels:
    app.kubernetes.io/name: kubescale-jaeger
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: kubescale-jaeger
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kubescale-jaeger
    spec:
      containers:
        - name: jaeger
          image: jaegertracing/all-in-one:1.57
          env:
            - name: COLLECTOR_OTLP_ENABLED
              value: "true"
          ports:
            - name: otlp-grpc
              containerPort: 4317
            - name: otlp-http
              containerPort: 4318
            - name: ui
              containerPort: 16686
---
apiVersion: v1
kind: Service
metadata:
  name: kubescale-jaeger
spec:
  type: ClusterIP
  ports:
    - name: otlp-grpc
      port: 4317
      targetPort: 4317
    - name: otlp-http
      port: 4318
      targetPort: 4318
    - name: ui
      port: 16686
      targetPort: 16686
  selector:
    app.kubernetes.io/name: kubescale-jaeger
EOF
fi

echo ">>> Waiting for Jaeger Pod to reach Ready state..."
kubectl rollout status deployment/kubescale-jaeger -n "${NAMESPACE}" --timeout=120s || true

echo ""
echo "======================================================================"
echo "  [SUCCESS] OpenTelemetry & Jaeger Tracing Stack Deployed!"
echo "  OTLP gRPC Port: 4317"
echo "  OTLP HTTP Port: 4318"
echo "  Jaeger Web UI Port: 16686"
echo ""
echo "  To access the Jaeger UI locally:"
echo "  kubectl port-forward svc/kubescale-jaeger -n ${NAMESPACE} 16686:16686"
echo "  URL: http://localhost:16686"
echo "======================================================================"
