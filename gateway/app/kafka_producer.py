import json
import logging
import time
from typing import Any, Dict, Optional

try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    KafkaProducer = None
    KafkaError = Exception

from app.config import settings

logger = logging.getLogger(__name__)


class ResilientKafkaProducer:
    """
    Kafka Producer client configured for high-throughput, low-latency streaming
    to the Strimzi Kafka Operator cluster.
    Includes circuit-breaking fallback for offline or local testing environments.
    """

    def __init__(self, bootstrap_servers: Optional[str] = None):
        self.bootstrap_servers = bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS
        self._producer: Optional[KafkaProducer] = None
        self._is_connected = False

    def get_producer(self) -> Optional[KafkaProducer]:
        """Lazy-initialize KafkaProducer instance."""
        if not KAFKA_AVAILABLE or not settings.KAFKA_ENABLED:
            return None

        if self._producer is None:
            try:
                self._producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers.split(","),
                    client_id=settings.KAFKA_CLIENT_ID,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    key_serializer=lambda k: k.encode("utf-8") if k else None,
                    acks="all",  # Guaranteed delivery across Strimzi ISR
                    retries=3,
                    max_in_flight_requests_per_connection=1,
                    request_timeout_ms=5000,
                    api_version_auto_timeout_ms=3000,
                )
                self._is_connected = True
                logger.info("Kafka producer initialized for %s", self.bootstrap_servers)
            except Exception as e:
                logger.warning(
                    "Kafka broker unreachable at %s: %s. Operating in simulated queue mode.",
                    self.bootstrap_servers,
                    str(e),
                )
                self._producer = None
                self._is_connected = False

        return self._producer

    def is_healthy(self) -> bool:
        """Verify broker connection."""
        if not settings.KAFKA_ENABLED:
            return True
        if not KAFKA_AVAILABLE:
            return False
        try:
            prod = self.get_producer()
            return prod is not None and prod.bootstrap_connected()
        except Exception:
            return False

    def publish_event(
        self, topic: str, key: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Publish an inference task payload to a Kafka topic.
        Returns partition and offset metadata, or simulated response in mock mode.
        """
        prod = self.get_producer()

        if prod is None:
            logger.info(
                "Mock Kafka publishing event to topic='%s', key='%s'", topic, key
            )
            return {
                "topic": topic,
                "partition": 0,
                "offset": int(time.time() * 1000) % 100000,
                "simulated": True,
            }

        try:
            future = prod.send(topic, key=key, value=payload)
            record_metadata = future.get(timeout=5.0)
            return {
                "topic": record_metadata.topic,
                "partition": record_metadata.partition,
                "offset": record_metadata.offset,
                "simulated": False,
            }
        except Exception as e:
            logger.error("Failed to publish message to topic %s: %s", topic, str(e))
            raise

    def close(self):
        """Flush and close producer connections."""
        if self._producer:
            try:
                self._producer.flush(timeout=3.0)
                self._producer.close(timeout=3.0)
            except Exception:
                pass
            self._producer = None
            self._is_connected = False


# Global singleton instance
kafka_producer = ResilientKafkaProducer()
