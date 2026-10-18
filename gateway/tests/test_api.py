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
