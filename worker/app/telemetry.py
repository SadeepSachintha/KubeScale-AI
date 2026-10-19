"""
OpenTelemetry Distributed Tracing & W3C Context Propagation for Async Worker.
Enables tracing of Kafka batch polling, micro-batch Triton inference, and offset commits.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
import os
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode, Tracer
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    from opentelemetry.sdk.resources import Resource
    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False
    trace = None
    Tracer = None

_global_tracer: Optional[Any] = None
_propagator = TraceContextTextMapPropagator() if OPENTELEMETRY_AVAILABLE else None


class DummySpan:
    """Fallback no-op span when OpenTelemetry is unavailable or disabled."""
    def set_attribute(self, key: str, value: Any):
        pass

    def set_status(self, status: Any, description: Optional[str] = None):
        pass

    def record_exception(self, exception: Exception):
        pass

    def get_span_context(self):
        class DummySpanContext:
            trace_id = 0
            span_id = 0
            is_valid = False
        return DummySpanContext()


def init_tracer(
    service_name: str = "kubescale-worker",
    environment: str = "dev",
    endpoint: Optional[str] = None,
    sampling_ratio: float = 1.0,
) -> Any:
    """Initialize OpenTelemetry TracerProvider for worker process."""
    global _global_tracer

    if not OPENTELEMETRY_AVAILABLE:
        logger.warning("OpenTelemetry SDK not installed; operating with no-op tracer fallback.")
        _global_tracer = DummySpan()
        return _global_tracer

    try:
        resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
            "deployment.environment": environment,
            "k8s.cluster.name": "kubescale-ai-eks",
        })

        sampler = TraceIdRatioBased(sampling_ratio)
        provider = TracerProvider(resource=resource, sampler=sampler)

        otlp_endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info("Initialized Worker OpenTelemetry OTLP Exporter: %s", otlp_endpoint)
            except Exception as exp_err:
                logger.debug("OTLP exporter unavailable (%s); using in-memory provider.", exp_err)

        trace.set_tracer_provider(provider)
        _global_tracer = trace.get_tracer(service_name)
        logger.info("OpenTelemetry tracer successfully initialized for %s (%s)", service_name, environment)
        return _global_tracer

    except Exception as e:
        logger.error("Failed to initialize OpenTelemetry tracer in worker: %s", str(e))
        _global_tracer = DummySpan()
        return _global_tracer


def get_tracer(service_name: str = "kubescale-worker") -> Any:
    """Get active OpenTelemetry tracer or initialize a default instance."""
    global _global_tracer
    if _global_tracer is None:
        return init_tracer(service_name=service_name)
    return _global_tracer


def inject_trace_context(carrier: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Inject current W3C TraceContext into carrier."""
    if carrier is None:
        carrier = {}
    if OPENTELEMETRY_AVAILABLE and _propagator:
        try:
            _propagator.inject(carrier)
        except Exception as e:
            logger.debug("Trace context injection failed: %s", str(e))
    return carrier


def extract_trace_context(carrier: Dict[str, str]) -> Any:
    """Extract W3C TraceContext from carrier dictionary."""
    if OPENTELEMETRY_AVAILABLE and _propagator:
        try:
            return _propagator.extract(carrier)
        except Exception as e:
            logger.debug("Trace context extraction failed: %s", str(e))
    return None


def get_current_trace_id() -> str:
    """Return active 32-character hex trace ID for logging correlation."""
    if not OPENTELEMETRY_AVAILABLE:
        return "0" * 32
    try:
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.is_valid:
            return format(ctx.trace_id, "032x")
    except Exception:
        pass
    return "0" * 32


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None, context: Any = None) -> Iterator[Any]:
    """Context manager for creating spans with safe fallback handling."""
    tracer = get_tracer()
    if not OPENTELEMETRY_AVAILABLE or isinstance(tracer, DummySpan):
        yield DummySpan()
        return

    try:
        with tracer.start_as_current_span(name, context=context) as span:
            if attributes:
                for k, v in attributes.items():
                    span.set_attribute(k, str(v) if not isinstance(v, (int, float, bool)) else v)
            yield span
    except Exception as exc:
        if OPENTELEMETRY_AVAILABLE:
            try:
                current_span = trace.get_current_span()
                current_span.set_status(Status(StatusCode.ERROR, str(exc)))
                current_span.record_exception(exc)
            except Exception:
                pass
        raise
