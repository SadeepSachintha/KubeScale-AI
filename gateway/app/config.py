from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized configuration for KubeScale AI Gateway.
    Reads from environment variables and ConfigMaps.
    """
    PROJECT_NAME: str = "KubeScale AI Gateway"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"

    # Gateway Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 2

    # Triton Inference Server settings
    # In Kubernetes, this connects to the inference ClusterIP service over gRPC (port 8001)
    TRITON_GRPC_URL: str = "kubescale-inference:8001"
    TRITON_HTTP_URL: str = "kubescale-inference:8000"
    TRITON_TIMEOUT_SECONDS: float = 5.0
    TRITON_RETRY_ATTEMPTS: int = 3
    DEFAULT_MODEL_NAME: str = "sentiment_onnx"
    DEFAULT_MODEL_VERSION: str = "1"

    # Strimzi Kafka Streaming settings
    # In Kubernetes, this resolves to the Strimzi bootstrap service
    KAFKA_BOOTSTRAP_SERVERS: str = "kubescale-kafka-bootstrap:9092"
    KAFKA_ENABLED: bool = True
    KAFKA_INFERENCE_REQUESTS_TOPIC: str = "inference-requests"
    KAFKA_INFERENCE_RESULTS_TOPIC: str = "inference-results"
    KAFKA_CLIENT_ID: str = "kubescale-gateway"

    # OpenTelemetry Distributed Tracing & APM
    OTEL_ENABLED: bool = True
    OTEL_SERVICE_NAME: str = "kubescale-gateway"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://kubescale-otel-collector:4317"
    OTEL_SAMPLING_RATIO: float = 1.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
