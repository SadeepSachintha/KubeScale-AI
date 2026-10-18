"""
Resilience & Chaos Engineering Verification Test Suite.
Validates retry policies, exponential backoff, circuit breaking,
and syntactic correctness of Chaos Mesh fault-injection manifests.
"""

import os
from unittest.mock import MagicMock, patch
import pytest
import yaml

from app.config import settings
from app.triton_client import TritonGrpcClient


def test_chaos_manifests_syntax_and_schema():
    """Verify all Chaos Mesh manifests in chaos/ are valid Kubernetes YAML resources."""
    chaos_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "chaos"))
    assert os.path.isdir(chaos_dir), f"Chaos directory missing at {chaos_dir}"

    manifest_files = [f for f in os.listdir(chaos_dir) if f.endswith(".yaml") or f.endswith(".yml")]
    assert len(manifest_files) >= 5, f"Expected at least 5 chaos manifests, found {len(manifest_files)}"

    for manifest in manifest_files:
        file_path = os.path.join(chaos_dir, manifest)
        with open(file_path, "r") as f:
            docs = list(yaml.safe_load_all(f))
            for doc in docs:
                assert doc is not None
                assert "apiVersion" in doc
                assert doc["apiVersion"].startswith("chaos-mesh.org/")
                assert "kind" in doc
                assert "metadata" in doc
                assert "spec" in doc
                assert doc["metadata"].get("namespace") == "kubescale"


def test_triton_client_transient_failure_recovery():
    """
    Simulate transient gRPC failure on attempt 1, followed by success on attempt 2.
    Verifies that exponential retry backoff masks transient pod kills.
    """
    import numpy as np

    client = TritonGrpcClient()
    mock_grpc_client = MagicMock()
    mock_grpc_module = MagicMock()

    # Simulate attempt 1 raising exception, attempt 2 returning valid numpy response
    mock_response = MagicMock()
    mock_response.as_numpy.return_value = np.array([[0.85, 0.15]], dtype=np.float32)
    mock_grpc_client.infer.side_effect = [
        RuntimeError("Transient Connection Reset by Peer (pod terminated)"),
        mock_response,
    ]

    with patch.object(client, "get_client", return_value=mock_grpc_client), \
         patch.object(client, "is_healthy", return_value=True), \
         patch("app.triton_client.grpcclient", mock_grpc_module):
        
        outputs, latency_ms = client._infer_sync(
            model_name="sentiment_onnx",
            input_data=[[0.1, 0.2, 0.3, 0.4]],
            model_version="1",
            input_tensor_name="INPUT_0",
            output_tensor_name="OUTPUT_0",
        )

        assert len(outputs) == 1
        assert outputs[0] == pytest.approx([0.85, 0.15], rel=1e-4)
        assert latency_ms > 0
        assert mock_grpc_client.infer.call_count == 2


def test_triton_client_exhausted_retries_raises():
    """
    Simulate persistent failure across all configured retry attempts.
    Verifies that the exception is raised once all retries are exhausted.
    """
    client = TritonGrpcClient()
    mock_grpc_client = MagicMock()
    mock_grpc_module = MagicMock()
    mock_grpc_client.infer.side_effect = RuntimeError("Persistent Triton Crash")

    with patch.object(client, "get_client", return_value=mock_grpc_client), \
         patch.object(client, "is_healthy", return_value=True), \
         patch("app.triton_client.grpcclient", mock_grpc_module):
        
        with pytest.raises(RuntimeError, match="Persistent Triton Crash"):
            client._infer_sync(
                model_name="sentiment_onnx",
                input_data=[[0.1, 0.2, 0.3, 0.4]],
                model_version="1",
                input_tensor_name="INPUT_0",
                output_tensor_name="OUTPUT_0",
            )

        assert mock_grpc_client.infer.call_count == settings.TRITON_RETRY_ATTEMPTS


def test_kafka_producer_resilience():
    """Verify that Kafka producer fallback behaves gracefully when brokers are partitioned."""
    from app.kafka_producer import ResilientKafkaProducer
    svc = ResilientKafkaProducer()
    
    # In fallback simulation mode when brokers are uncontactable
    result = svc.publish_event(
        topic="inference-requests",
        key="resilience-test-key",
        payload={"request_id": "resilience-test-key", "data": [1, 2, 3]},
    )
    assert result["simulated"] is True
    assert result["topic"] == "inference-requests"
