import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import settings
from app.kafka_producer import kafka_producer
from app.schemas import (
    AsyncInferenceRequest,
    AsyncInferenceResponse,
    HealthStatus,
    InferenceRequest,
    InferenceResponse,
    ModelControlResponse,
    ModelMetadataResponse,
    ModelRepositoryItem,
    ModelRepositoryResponse,
)
from app.telemetry import (
    extract_trace_context,
    get_current_trace_id,
    init_tracer,
    inject_trace_context,
    trace_span,
)
from app.triton_client import triton_client

# ------------------------------------------------------------------------------
# Logging Setup
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("kubescale-gateway")

# ------------------------------------------------------------------------------
# Prometheus Instrumentation Metrics
# ------------------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "kubescale_gateway_requests_total",
    "Total HTTP requests received by gateway",
    ["method", "endpoint", "status_code"],
)
REQUEST_LATENCY = Histogram(
    "kubescale_gateway_request_duration_seconds",
    "HTTP request latency in seconds",
    ["endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
INFERENCE_LATENCY = Histogram(
    "kubescale_triton_inference_duration_seconds",
    "Time taken for Triton gRPC inference in seconds",
    ["model_name"],
    buckets=[0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0],
)
KAFKA_PUBLISH_COUNT = Counter(
    "kubescale_kafka_events_published_total",
    "Total asynchronous events published to Strimzi Kafka",
    ["topic", "status"],
)
MODEL_CONTROL_COUNT = Counter(
    "kubescale_model_control_actions_total",
    "Total dynamic model control actions executed against Triton server",
    ["action", "model_name", "status"],
)

START_TIME = time.time()


# ------------------------------------------------------------------------------
# Lifespan Management
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle startup and teardown management."""
    logger.info("Initializing KubeScale AI Gateway...")
    # Initialize OpenTelemetry Distributed Tracer
    if settings.OTEL_ENABLED:
        init_tracer(
            service_name=settings.OTEL_SERVICE_NAME,
            environment=settings.ENVIRONMENT,
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            sampling_ratio=settings.OTEL_SAMPLING_RATIO,
        )
    # Initialize background connections
    _ = triton_client.get_client()
    if settings.KAFKA_ENABLED:
        _ = kafka_producer.get_producer()
    yield
    logger.info("Shutting down KubeScale AI Gateway...")
    triton_client.close()
    kafka_producer.close()


# ------------------------------------------------------------------------------
# FastAPI Application
# ------------------------------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Production-grade API Gateway for Triton Inference Server and Strimzi Kafka. "
        "Enables horizontal scaling, dynamic batching, and decoupling of compute-heavy ML."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    """Measure request latency and record Prometheus metrics."""
    start_time = time.perf_counter()
    endpoint = request.url.path

    try:
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        ).inc()
        return response
    except Exception as exc:
        duration = time.perf_counter() - start_time
        REQUEST_LATENCY.labels(endpoint=endpoint).observe(duration)
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=500,
        ).inc()
        raise exc


# ------------------------------------------------------------------------------
# Health & Diagnostic Endpoints (Kubernetes Probes)
# ------------------------------------------------------------------------------
@app.get("/healthz", response_model=HealthStatus, tags=["Health"])
async def liveness_probe():
    """
    Kubernetes Liveness Probe: Verifies the process is alive and responsive.
    Failure triggers pod reboot.
    """
    return HealthStatus(
        status="UP",
        service="kubescale-gateway",
        environment=settings.ENVIRONMENT,
        triton_grpc_connected=triton_client.is_healthy(),
        kafka_connected=kafka_producer.is_healthy(),
        version=settings.VERSION,
        uptime_seconds=round(time.time() - START_TIME, 2),
    )


@app.get("/readyz", response_model=HealthStatus, tags=["Health"])
async def readiness_probe():
    """
    Kubernetes Readiness Probe: Verifies Triton gRPC backend readiness.
    If the inference backend is unavailable, the pod is removed from ingress traffic.
    """
    triton_ok = triton_client.is_healthy()
    # In strict production, fail if Triton is down; in dev allow starting
    is_ready = triton_ok or (settings.ENVIRONMENT == "dev")

    if not is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Triton inference backend is not ready.",
        )

    return HealthStatus(
        status="READY" if is_ready else "DEGRADED",
        service="kubescale-gateway",
        environment=settings.ENVIRONMENT,
        triton_grpc_connected=triton_ok,
        kafka_connected=kafka_producer.is_healthy(),
        version=settings.VERSION,
        uptime_seconds=round(time.time() - START_TIME, 2),
    )


@app.get("/metrics", tags=["Telemetry"])
async def metrics():
    """Expose Prometheus metrics for scraping by Prometheus Operator / Adapter."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", tags=["General"])
async def root():
    """Root metadata overview."""
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "docs_url": "/docs",
        "health_endpoint": "/healthz",
        "ready_endpoint": "/readyz",
        "metrics_endpoint": "/metrics",
        "repository_endpoint": "/v1/repository/index",
    }


# ------------------------------------------------------------------------------
# Model Inference Endpoints
# ------------------------------------------------------------------------------
@app.post(
    "/v1/models/{model_name}/predict",
    response_model=InferenceResponse,
    tags=["Inference"],
)
async def predict_sync(model_name: str, payload: InferenceRequest):
    """
    Synchronous ML Inference:
    Forwards input tensors over low-latency gRPC to Triton Inference Server.
    Triton dynamically batches requests across concurrent pods.
    Instrumented with OpenTelemetry distributed trace spans.
    """
    target_model = payload.model_name or model_name
    target_version = payload.model_version or "1"

    with trace_span(
        "gateway.predict_sync",
        attributes={
            "model.name": target_model,
            "model.version": target_version,
            "request.id": payload.request_id,
            "tensor.batch_size": len(payload.inputs),
        },
    ):
        infer_start = time.perf_counter()
        try:
            with trace_span(
                "triton.grpc_infer",
                attributes={
                    "model.name": target_model,
                    "model.version": target_version,
                    "triton.endpoint": settings.TRITON_GRPC_URL,
                },
            ):
                outputs, latency_ms = await triton_client.infer(
                    model_name=target_model,
                    input_data=payload.inputs,
                    model_version=target_version,
                )

            infer_duration = time.perf_counter() - infer_start
            INFERENCE_LATENCY.labels(model_name=target_model).observe(infer_duration)

            # Derive predicted class labels (argmax over output probabilities)
            predictions = []
            for row in outputs:
                if len(row) > 0:
                    predictions.append(int(row.index(max(row))))

            return InferenceResponse(
                request_id=payload.request_id,
                model_name=target_model,
                model_version=target_version,
                outputs=outputs,
                predictions=predictions,
                latency_ms=round(latency_ms, 2),
                backend="Triton-gRPC",
            )

        except Exception as e:
            logger.error(
                "Prediction error for model '%s', request_id=%s: %s",
                target_model,
                payload.request_id,
                str(e),
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Inference execution failed: {str(e)}",
            )


@app.post(
    "/v1/models/{model_name}/async-predict",
    response_model=AsyncInferenceResponse,
    tags=["Streaming Inference"],
)
async def predict_async(model_name: str, payload: AsyncInferenceRequest):
    """
    Asynchronous / Event-Driven ML Inference:
    Enqueues the inference payload into an enterprise Kafka topic (managed by Strimzi).
    Injects W3C TraceContext headers so consumer workers can link trace spans end-to-end.
    """
    target_topic = settings.KAFKA_INFERENCE_REQUESTS_TOPIC

    with trace_span(
        "gateway.predict_async.publish",
        attributes={
            "model.name": model_name,
            "request.id": payload.request_id,
            "kafka.topic": target_topic,
        },
    ):
        trace_context = inject_trace_context()
        event_payload = {
            "request_id": payload.request_id,
            "model_name": model_name,
            "inputs": payload.inputs,
            "callback_topic": payload.callback_topic,
            "metadata": payload.metadata,
            "trace_context": trace_context,
            "timestamp": time.time(),
        }

        try:
            publish_result = kafka_producer.publish_event(
                topic=target_topic,
                key=payload.request_id,
                payload=event_payload,
            )

            KAFKA_PUBLISH_COUNT.labels(topic=target_topic, status="success").inc()

            return AsyncInferenceResponse(
                request_id=payload.request_id,
                status="QUEUED",
                topic=publish_result["topic"],
                partition=publish_result.get("partition"),
                offset=publish_result.get("offset"),
                message="Inference job enqueued in Strimzi Kafka cluster with distributed trace context.",
            )

        except Exception as e:
            KAFKA_PUBLISH_COUNT.labels(topic=target_topic, status="error").inc()
            logger.error("Failed to enqueue async inference task: %s", str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to publish inference job to Kafka stream: {str(e)}",
            )


@app.get("/v1/models/{model_name}/status", tags=["Inference"])
async def model_status(model_name: str, version: Optional[str] = "1"):
    """Check Triton model readiness."""
    is_ready = triton_client.is_model_ready(model_name=model_name, model_version=version)
    return {
        "model_name": model_name,
        "version": version,
        "ready": is_ready,
    }


# ------------------------------------------------------------------------------
# Model Control & Dynamic Repository Endpoints (Zero-Downtime Hot-Reload)
# ------------------------------------------------------------------------------
@app.get(
    "/v1/repository/index",
    response_model=ModelRepositoryResponse,
    tags=["Model Control Plane"],
)
async def get_repository_index():
    """
    Triton Model Repository Index:
    Lists all models available in the shared model repository, their active version,
    and their operational state (READY vs UNAVAILABLE).
    """
    try:
        models_data = triton_client.get_model_repository_index()
        return ModelRepositoryResponse(
            models=[ModelRepositoryItem(**m) for m in models_data],
            total_models=len(models_data),
            control_mode="explicit",
        )
    except Exception as e:
        logger.error("Failed to query model repository index: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch model repository index: {str(e)}",
        )


@app.post(
    "/v1/repository/models/{model_name}/load",
    response_model=ModelControlResponse,
    tags=["Model Control Plane"],
)
async def load_model(model_name: str):
    """
    Explicit Model Loading & Zero-Downtime Hot Reload:
    Dynamically loads or reloads model weights into Triton runtime memory
    without dropping in-flight traffic or restarting worker pods.
    """
    try:
        res = triton_client.load_model(model_name=model_name)
        MODEL_CONTROL_COUNT.labels(action="load", model_name=model_name, status="success").inc()
        return ModelControlResponse(**res)
    except Exception as e:
        MODEL_CONTROL_COUNT.labels(action="load", model_name=model_name, status="error").inc()
        logger.error("Failed to dynamically load model '%s': %s", model_name, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to dynamically load model '{model_name}': {str(e)}",
        )


@app.post(
    "/v1/repository/models/{model_name}/unload",
    response_model=ModelControlResponse,
    tags=["Model Control Plane"],
)
async def unload_model(model_name: str):
    """
    Explicit Model Unloading:
    Evicts an inactive model from Triton runtime memory to reclaim GPU/CPU resources.
    """
    try:
        res = triton_client.unload_model(model_name=model_name)
        MODEL_CONTROL_COUNT.labels(action="unload", model_name=model_name, status="success").inc()
        return ModelControlResponse(**res)
    except KeyError:
        MODEL_CONTROL_COUNT.labels(action="unload", model_name=model_name, status="not_found").inc()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_name}' not found in model repository.",
        )
    except Exception as e:
        MODEL_CONTROL_COUNT.labels(action="unload", model_name=model_name, status="error").inc()
        logger.error("Failed to unload model '%s': %s", model_name, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unload model '{model_name}': {str(e)}",
        )


@app.get(
    "/v1/models/{model_name}/metadata",
    response_model=ModelMetadataResponse,
    tags=["Model Control Plane"],
)
async def get_model_metadata(model_name: str, version: Optional[str] = "1"):
    """
    Model Architectural Metadata:
    Inspect input/output tensor shapes, datatypes, and runtime backend for a loaded model.
    """
    try:
        meta = triton_client.get_model_metadata(model_name=model_name, model_version=version)
        return ModelMetadataResponse(**meta)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_name}' not registered in repository.",
        )
    except RuntimeError as re:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(re),
        )
    except Exception as e:
        logger.error("Failed to fetch metadata for model '%s': %s", model_name, str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve model metadata: {str(e)}",
        )

