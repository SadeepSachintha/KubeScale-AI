import pytest
from worker.app.consumer import AsyncInferenceWorker


@pytest.fixture
def worker():
    w = AsyncInferenceWorker()
    return w


def test_empty_micro_batch(worker):
    """Test handling of empty message batch."""
    results = worker.process_micro_batch([])
    assert results == []


def test_micro_batch_processing(worker):
    """Test multi-record micro-batching and tensor slicing."""
    mock_records = [
        {
            "request_id": "req-1",
            "model_name": "sentiment_onnx",
            "inputs": [[0.5, -0.2, 0.1, 0.9]],
            "callback_topic": "inference-results",
        },
        {
            "request_id": "req-2",
            "model_name": "sentiment_onnx",
            "inputs": [
                [-0.8, 0.3, -0.1, 0.2],
                [0.1, 0.2, 0.3, 0.4],
            ],
            "callback_topic": "custom-results",
        },
    ]

    results = worker.process_micro_batch(mock_records)
    assert len(results) == 2

    # Check record 1
    assert results[0]["request_id"] == "req-1"
    assert results[0]["status"] == "COMPLETED"
    assert len(results[0]["outputs"]) == 1
    assert len(results[0]["predictions"]) == 1
    assert results[0]["callback_topic"] == "inference-results"

    # Check record 2
    assert results[1]["request_id"] == "req-2"
    assert results[1]["status"] == "COMPLETED"
    assert len(results[1]["outputs"]) == 2
    assert len(results[1]["predictions"]) == 2
    assert results[1]["callback_topic"] == "custom-results"


def test_worker_readiness_in_dev(worker):
    """In development mode, worker readiness check returns True."""
    assert worker.is_ready() is True


def test_worker_trace_context_propagation(worker):
    """Verify that incoming W3C trace context is preserved across Kafka micro-batch processing."""
    sample_traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    mock_records = [
        {
            "request_id": "traced-req-1",
            "model_name": "sentiment_onnx",
            "inputs": [[0.1, 0.2, 0.3, 0.4]],
            "callback_topic": "inference-results",
            "trace_context": {"traceparent": sample_traceparent},
        }
    ]

    results = worker.process_micro_batch(mock_records)
    assert len(results) == 1
    assert "trace_context" in results[0]
    assert results[0]["trace_context"].get("traceparent") == sample_traceparent


def test_worker_telemetry_span_creation():
    """Verify worker telemetry module creates spans and extracts context safely."""
    from worker.app.telemetry import (
        extract_trace_context,
        get_current_trace_id,
        init_tracer,
        inject_trace_context,
        trace_span,
    )

    tracer = init_tracer(service_name="test-worker", environment="test")
    assert tracer is not None

    carrier = {}
    with trace_span("test.worker_span", attributes={"batch.id": "b-123"}):
        inject_trace_context(carrier)
        assert "traceparent" in carrier

    extracted = extract_trace_context(carrier)
    assert extracted is not None

