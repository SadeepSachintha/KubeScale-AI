import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_endpoint():
    """Test API discovery endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert data["service"] == "KubeScale AI Gateway"
    assert data["docs_url"] == "/docs"


def test_liveness_probe():
    """Verify Kubernetes liveness probe returns UP."""
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"
    assert "uptime_seconds" in data


def test_readiness_probe():
    """Verify Kubernetes readiness probe."""
    response = client.get("/readyz")
    assert response.status_code in [200, 503]


def test_metrics_endpoint():
    """Verify Prometheus metrics are exposed."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "kubescale_gateway_requests_total" in response.text


def test_synchronous_prediction_simulation():
    """Test sync inference through gateway with mock/fallback."""
    payload = {
        "model_name": "sentiment_onnx",
        "inputs": [
            [0.1, 0.2, 0.3, 0.4],
            [-0.5, 0.8, -0.2, 0.1]
        ]
    }
    response = client.post("/v1/models/sentiment_onnx/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["model_name"] == "sentiment_onnx"
    assert len(data["outputs"]) == 2
    assert "latency_ms" in data
    assert "predictions" in data


def test_asynchronous_prediction():
    """Test async inference published to Kafka topic."""
    payload = {
        "model_name": "sentiment_onnx",
        "inputs": [
            [0.1, 0.2, 0.3, 0.4]
        ],
        "callback_topic": "inference-results"
    }
    response = client.post("/v1/models/sentiment_onnx/async-predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "QUEUED"
    assert data["topic"] == "inference-requests"
    assert "request_id" in data


def test_model_repository_index():
    """Test Triton model repository catalog discovery endpoint."""
    response = client.get("/v1/repository/index")
    assert response.status_code == 200
    data = response.json()
    assert data["control_mode"] == "explicit"
    assert data["total_models"] >= 2
    model_names = [m["name"] for m in data["models"]]
    assert "sentiment_onnx" in model_names
    assert "fraud_detection_onnx" in model_names


def test_model_metadata():
    """Test fetching model architecture metadata and IO tensor specs."""
    response = client.get("/v1/models/sentiment_onnx/metadata")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "sentiment_onnx"
    assert data["platform"] == "onnxruntime_onnx"
    assert len(data["inputs"]) > 0
    assert len(data["outputs"]) > 0


def test_dynamic_model_lifecycle_hot_reload():
    """
    Test full lifecycle of dynamic model hot-reload:
    1. Verify fraud_detection_onnx is initially UNAVAILABLE
    2. Attempt inference while unloaded (fails cleanly)
    3. Dynamically load model via Model Control API
    4. Confirm model is READY
    5. Execute inference successfully
    6. Dynamically unload model to free memory
    """
    # 1. Initially unallocated / unavailable
    res_status = client.get("/v1/models/fraud_detection_onnx/status")
    assert res_status.status_code == 200
    assert res_status.json()["ready"] is False

    # 2. Attempt inference while unallocated (should fail)
    infer_payload = {
        "model_name": "fraud_detection_onnx",
        "inputs": [[0.5] * 64]
    }
    infer_fail = client.post("/v1/models/fraud_detection_onnx/predict", json=infer_payload)
    assert infer_fail.status_code == 500
    assert "UNAVAILABLE" in infer_fail.json()["detail"]

    # 3. Dynamically load model without pod restart
    load_res = client.post("/v1/repository/models/fraud_detection_onnx/load")
    assert load_res.status_code == 200
    load_data = load_res.json()
    assert load_data["action"] == "LOAD"
    assert load_data["status"] == "SUCCESS"

    # 4. Confirm model is now READY
    res_ready = client.get("/v1/models/fraud_detection_onnx/status")
    assert res_ready.status_code == 200
    assert res_ready.json()["ready"] is True

    # 5. Execute inference successfully
    infer_ok = client.post("/v1/models/fraud_detection_onnx/predict", json=infer_payload)
    assert infer_ok.status_code == 200
    assert infer_ok.json()["model_name"] == "fraud_detection_onnx"
    assert len(infer_ok.json()["outputs"]) == 1

    # 6. Dynamically unload model
    unload_res = client.post("/v1/repository/models/fraud_detection_onnx/unload")
    assert unload_res.status_code == 200
    unload_data = unload_res.json()
    assert unload_data["action"] == "UNLOAD"
    assert unload_data["status"] == "SUCCESS"

    # Verify model is now UNAVAILABLE again
    res_after = client.get("/v1/models/fraud_detection_onnx/status")
    assert res_after.json()["ready"] is False


def test_unload_nonexistent_model():
    """Verify unloading a model not present in repository returns 404."""
    response = client.post("/v1/repository/models/nonexistent_model_xyz/unload")
    assert response.status_code == 404

