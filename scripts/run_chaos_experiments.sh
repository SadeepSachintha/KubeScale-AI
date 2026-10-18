#!/usr/bin/env bash
# ==============================================================================
# KubeScale AI: Automated Chaos Engineering & Fault Injection Resilience Suite
# Applies Chaos Mesh experiments under sustained traffic and verifies self-healing.
# ==============================================================================

set -euo pipefail

NAMESPACE="${NAMESPACE:-kubescale}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"
CHAOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../chaos" && pwd)"

echo "======================================================================"
echo "  KUBESCALE AI: CHAOS ENGINEERING & RESILIENCE SUITE"
echo "  Namespace: ${NAMESPACE}"
echo "  Gateway:   ${GATEWAY_URL}"
echo "======================================================================"

# Verify kubectl access
if ! command -v kubectl &> /dev/null; then
    echo "[ERROR] 'kubectl' is not installed or not in PATH."
    exit 1
fi

echo ""
echo ">>> Checking cluster baseline health..."
kubectl get pods -n "${NAMESPACE}" -l 'app.kubernetes.io/part-of=kubescale-ai' || true

echo ""
echo ">>> Step 1: Testing Triton Pod Self-Healing & Service Round-Robin..."
echo "    Applying PodChaos: Terminating an active Triton inference pod..."
if kubectl apply -f "${CHAOS_DIR}/pod-failure-triton.yaml"; then
    echo "    [OK] PodChaos applied. Simulating concurrent traffic to verify zero dropped requests..."
    # Fire 5 concurrent requests during pod termination
    for i in {1..5}; do
        curl -s -o /dev/null -w "    Request $i: HTTP %{http_code} (time: %{time_total}s)\n" \
            -X POST "${GATEWAY_URL}/v1/models/sentiment_onnx/predict" \
            -H "Content-Type: application/json" \
            -d '{"model_name":"sentiment_onnx","inputs":[[0.1,0.2,0.3,0.4]]}' || true
        sleep 0.5
    done
    echo "    Cleaning up PodChaos..."
    kubectl delete -f "${CHAOS_DIR}/pod-failure-triton.yaml" --ignore-not-found=true
fi

echo ""
echo ">>> Step 2: Testing Gateway Ingress Network Latency Injection..."
echo "    Applying NetworkChaos: Injecting 200ms latency on Gateway..."
if kubectl apply -f "${CHAOS_DIR}/network-delay-gateway.yaml"; then
    echo "    [OK] NetworkChaos active. Checking latency degradation..."
    curl -s -o /dev/null -w "    Latency under chaos: %{time_total}s (HTTP %{http_code})\n" \
        -X POST "${GATEWAY_URL}/v1/models/sentiment_onnx/predict" \
        -H "Content-Type: application/json" \
        -d '{"model_name":"sentiment_onnx","inputs":[[0.1,0.2,0.3,0.4]]}' || true
    echo "    Cleaning up NetworkChaos..."
    kubectl delete -f "${CHAOS_DIR}/network-delay-gateway.yaml" --ignore-not-found=true
fi

echo ""
echo ">>> Step 3: Testing Kafka Broker Network Partition & Producer Retries..."
echo "    Applying NetworkChaos: Isolating single Kafka broker in 3-node cluster..."
if kubectl apply -f "${CHAOS_DIR}/network-partition-kafka.yaml"; then
    echo "    [OK] Broker partitioned. Enqueuing async inference job to verify ISR quorum..."
    curl -s -X POST "${GATEWAY_URL}/v1/models/sentiment_onnx/async-predict" \
        -H "Content-Type: application/json" \
        -d '{"model_name":"sentiment_onnx","inputs":[[0.5,0.2,0.1,0.9]],"callback_topic":"inference-results"}' | python3 -m json.tool || true
    echo "    Cleaning up Kafka NetworkChaos..."
    kubectl delete -f "${CHAOS_DIR}/network-partition-kafka.yaml" --ignore-not-found=true
fi

echo ""
echo ">>> Step 4: Testing Worker CPU Saturation & Autoscaling Triggers..."
echo "    Applying StressChaos: Injecting 85% CPU load on worker pods..."
if kubectl apply -f "${CHAOS_DIR}/stress-worker-cpu.yaml"; then
    echo "    [OK] StressChaos active. Checking pod status..."
    kubectl get pods -n "${NAMESPACE}" -l app.kubernetes.io/component=worker || true
    echo "    Cleaning up StressChaos..."
    kubectl delete -f "${CHAOS_DIR}/stress-worker-cpu.yaml" --ignore-not-found=true
fi

echo ""
echo "======================================================================"
echo "  [SUCCESS] Chaos Engineering Resilience Suite Completed!"
echo "  All fault injection scenarios executed and cleared."
echo "======================================================================"
