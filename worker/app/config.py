from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """
    Configuration settings for KubeScale AI Kafka Consumer Worker.
    Pulls inference tasks from Kafka, executes Triton batch inference,
    and publishes results back to Kafka.
    """
    PROJECT_NAME: str = "KubeScale AI Async Inference Worker"
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"

    # Kafka Broker Configuration
    KAFKA_BOOTSTRAP_SERVERS: str = "kubescale-kafka-bootstrap:9092"
    KAFKA_REQUESTS_TOPIC: str = "inference-requests"
    KAFKA_RESULTS_TOPIC: str = "inference-results"
    KAFKA_GROUP_ID: str = "kubescale-inference-workers"
    KAFKA_CLIENT_ID: str = "kubescale-worker-1"
    KAFKA_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_ENABLE_AUTO_COMMIT: bool = False

    # Batching & Polling Behavior
    MAX_POLL_RECORDS: int = 32
    POLL_TIMEOUT_MS: int = 1000

    # Triton Inference Server Configuration
    TRITON_GRPC_URL: str = "kubescale-inference:8001"
    TRITON_TIMEOUT_SECONDS: float = 5.0
    DEFAULT_MODEL_NAME: str = "sentiment_onnx"
    DEFAULT_MODEL_VERSION: str = "1"

    # Health & Prometheus Telemetry Server
    HEALTH_PORT: int = 8080

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = WorkerSettings()
