from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class InferenceRequest(BaseModel):
    """
    Synchronous inference payload for Triton / ONNX models.
    Supports either direct 2D numerical tensor data or feature arrays.
    """
    request_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID tracing the inference request across gateway and Triton"
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Target model name in Triton model repository"
    )
    model_version: Optional[str] = Field(
        default="1",
        description="Target model version"
    )
    # Tensor data: list of lists (e.g. [[0.1, 0.5, ...]]) or 1D list of floats
    inputs: List[List[float]] = Field(
        ...,
        description="Input tensor data shaped [batch_size, feature_dim] (e.g. [[0.5, 1.2, -0.4, ...]])"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional hyperparameter overrides or flags passed to Triton"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                "model_name": "sentiment_onnx",
                "model_version": "1",
                "inputs": [
                    [0.12, 0.45, -0.23, 0.88, 0.15, -0.09, 0.72, 0.31]
                ],
                "parameters": {"binary_threshold": 0.5}
            }
        }
    )


class InferenceResponse(BaseModel):
    """
    Standardized inference response containing predictions and telemetry.
    """
    request_id: str
    model_name: str
    model_version: str
    outputs: List[List[float]]
    predictions: Optional[List[Any]] = None
    latency_ms: float
    backend: str = "Triton-gRPC"
    timestamp: float = Field(default_factory=time.time)


class AsyncInferenceRequest(BaseModel):
    """
    Asynchronous payload published to Strimzi Kafka topic for decoupled,
    backpressure-safe batch inference.
    """
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    model_name: str = "sentiment_onnx"
    inputs: List[List[float]]
    callback_topic: Optional[str] = "inference-results"
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class AsyncInferenceResponse(BaseModel):
    """
    Immediate acknowledgement that the inference request has been enqueued in Kafka.
    """
    request_id: str
    status: str = "QUEUED"
    topic: str
    partition: Optional[int] = None
    offset: Optional[int] = None
    message: str = "Inference job successfully published to Kafka topic for stream processing."
    timestamp: float = Field(default_factory=time.time)


class HealthStatus(BaseModel):
    """
    Liveness and Readiness probe status schema.
    """
    status: str
    service: str
    environment: str
    triton_grpc_connected: bool
    kafka_connected: bool
    version: str
    uptime_seconds: float


class ModelRepositoryItem(BaseModel):
    """
    Model entry in Triton's repository catalog.
    """
    name: str = Field(..., description="Unique model identifier in repository")
    version: str = Field(default="1", description="Model version string")
    state: str = Field(..., description="Triton model state: READY, UNAVAILABLE, LOADING, or UNLOADING")
    reason: Optional[str] = Field(default="", description="Diagnostic message or state reasoning")


class ModelRepositoryResponse(BaseModel):
    """
    Repository index catalog response.
    """
    models: List[ModelRepositoryItem] = Field(default_factory=list)
    total_models: int = Field(default=0)
    control_mode: str = Field(default="explicit", description="Triton control mode: explicit, poll, or none")


class ModelControlResponse(BaseModel):
    """
    Action result for explicit model loading or unloading in Triton.
    """
    model_name: str
    action: str = Field(..., description="Action attempted: LOAD or UNLOAD")
    status: str = Field(..., description="Action outcome: SUCCESS or FAILED")
    message: str
    timestamp: float = Field(default_factory=time.time)


class ModelTensorSpec(BaseModel):
    """
    Specification of an input or output tensor.
    """
    name: str
    datatype: str
    shape: List[int]


class ModelMetadataResponse(BaseModel):
    """
    Triton model architecture and IO tensor metadata.
    """
    name: str
    versions: List[str]
    platform: str
    inputs: List[ModelTensorSpec]
    outputs: List[ModelTensorSpec]

