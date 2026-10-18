#!/usr/bin/env bash
# ==============================================================================
# KubeScale AI: Dynamic Multi-Model Serving & Triton Live Reload Demonstration
# Demonstrates zero-downtime model loading, dynamic batching, and memory recovery.
# ==============================================================================

set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"

echo "======================================================================"
echo "  KUBESCALE AI: TRITON DYNAMIC MODEL CONTROL PLANE DEMO"
echo "  Endpoint: ${GATEWAY_URL}"
echo "======================================================================"

echo ""
echo ">>> 1. Inspecting Triton Model Repository Index (/v1/repository/index)..."
curl -s -X GET "${GATEWAY_URL}/v1/repository/index" | python3 -m json.tool

echo ""
echo ">>> 2. Verifying 'fraud_detection_onnx' readiness before loading..."
curl -s -X GET "${GATEWAY_URL}/v1/models/fraud_detection_onnx/status" | python3 -m json.tool

echo ""
echo ">>> 3. Dynamically Loading 'fraud_detection_onnx' into Triton Runtime..."
echo "    (Triton pulls model weights and creates CPU/GPU execution instances without restarting pods)"
curl -s -X POST "${GATEWAY_URL}/v1/repository/models/fraud_detection_onnx/load" | python3 -m json.tool

echo ""
echo ">>> 4. Querying Architecture & Tensor Specs (/v1/models/fraud_detection_onnx/metadata)..."
curl -s -X GET "${GATEWAY_URL}/v1/models/fraud_detection_onnx/metadata" | python3 -m json.tool

echo ""
echo ">>> 5. Executing Synchronous Inference on newly loaded 'fraud_detection_onnx'..."
SAMPLE_INPUT="[$(python3 -c "import random; print(','.join(str(round(random.uniform(-1, 1), 4)) for _ in range(64)))")]"
curl -s -X POST "${GATEWAY_URL}/v1/models/fraud_detection_onnx/predict" \
  -H "Content-Type: application/json" \
  -d "{
    \"model_name\": \"fraud_detection_onnx\",
    \"inputs\": [${SAMPLE_INPUT}]
  }" | python3 -m json.tool

echo ""
echo ">>> 6. Unloading 'fraud_detection_onnx' to reclaim memory / compute resources..."
curl -s -X POST "${GATEWAY_URL}/v1/repository/models/fraud_detection_onnx/unload" | python3 -m json.tool

echo ""
echo ">>> 7. Verifying final repository state..."
curl -s -X GET "${GATEWAY_URL}/v1/repository/index" | python3 -m json.tool

echo ""
echo "======================================================================"
echo "  [SUCCESS] Triton Live Reload & Multi-Model Serving Demonstration Complete!"
echo "======================================================================"
