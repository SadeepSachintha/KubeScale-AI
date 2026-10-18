#!/usr/bin/env bash
# ==============================================================================
# OpenTelemetry Distributed Tracing & W3C Context Propagation Demo
# Generates traced synchronous and asynchronous inference workloads,
# inspects traceparents, and guides waterfall visualization in Jaeger.
# ==============================================================================

set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"

echo "======================================================================"
echo "  KUBESCALE AI: OPENTELEMETRY DISTRIBUTED TRACING DEMO"
echo "  Gateway: ${GATEWAY_URL}"
echo "======================================================================"

echo ""
echo ">>> 1. Dispatching Synchronous Inference with Distributed Trace Spans..."
echo "    Spans generated: [gateway.predict_sync] -> [triton.grpc_infer]"
curl -s -X POST "${GATEWAY_URL}/v1/models/sentiment_onnx/predict" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "sentiment_onnx",
    "inputs": [[0.12, 0.45, -0.23, 0.88, 0.15, -0.09, 0.72, 0.31]]
  }' | python3 -m json.tool

echo ""
echo ">>> 2. Dispatching Asynchronous Streaming Inference with W3C Context Injection..."
echo "    Spans generated: [gateway.predict_async.publish] -> Kafka Header [traceparent]"
echo "                     -> [worker.process_micro_batch] -> [worker.triton_batch_infer]"
curl -s -X POST "${GATEWAY_URL}/v1/models/sentiment_onnx/async-predict" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "sentiment_onnx",
    "inputs": [[-0.5, 0.8, -0.2, 0.1]],
    "callback_topic": "inference-results"
  }' | python3 -m json.tool

echo ""
echo ">>> 3. Inspecting Active Trace Attributes from Telemetry Module..."
python3 -c "
from gateway.app.telemetry import init_tracer, trace_span, inject_trace_context
tracer = init_tracer(service_name='kubescale-gateway-demo', environment='demo')
carrier = {}
with trace_span('demo.inference_workflow', attributes={'model': 'sentiment_onnx', 'batch_size': 1}):
    inject_trace_context(carrier)
print('Generated W3C Trace Carrier:', carrier)
print('Trace ID:', carrier.get('traceparent', '').split('-')[1] if 'traceparent' in carrier else 'N/A')
"

echo ""
echo "======================================================================"
echo "  [SUCCESS] Distributed Tracing Demonstration Executed Successfully!"
echo "  To view the interactive trace waterfall & latency breakdown:"
echo "  1. Forward Jaeger UI: kubectl port-forward svc/kubescale-jaeger 16686:16686 -n kubescale"
echo "  2. Open browser at:   http://localhost:16686"
echo "  3. Select Service:    'kubescale-gateway' or 'kubescale-worker'"
echo "======================================================================"
