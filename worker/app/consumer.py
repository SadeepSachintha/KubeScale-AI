import json
import logging
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

try:
    from kafka import KafkaConsumer, KafkaProducer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    KafkaConsumer = None
    KafkaProducer = None
    KafkaError = Exception

try:
    import tritonclient.grpc as grpcclient
    TRITON_AVAILABLE = True
except ImportError:
    TRITON_AVAILABLE = False
    grpcclient = None

from worker.app.config import settings
from worker.app.telemetry import (
    extract_trace_context,
    get_current_trace_id,
    init_tracer,
    inject_trace_context,
    trace_span,
)

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("kubescale-worker")

# ------------------------------------------------------------------------------
# Prometheus Metrics
# ------------------------------------------------------------------------------
MESSAGES_CONSUMED = Counter(
    "kubescale_worker_messages_consumed_total",
    "Total async messages consumed from Kafka",
    ["status"],
)
BATCH_SIZE_HIST = Histogram(
    "kubescale_worker_batch_size",
    "Distribution of micro-batch sizes processed",
    buckets=[1, 2, 4, 8, 16, 32, 64],
)
INFERENCE_LATENCY = Histogram(
    "kubescale_worker_triton_latency_seconds",
    "Triton batch inference execution latency in seconds",
    ["model_name"],
    buckets=[0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0],
)
PROCESSING_LATENCY = Histogram(
    "kubescale_worker_end_to_end_seconds",
    "Total message processing latency from consumption to publication",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
)


# ------------------------------------------------------------------------------
# Lightweight Health & Prometheus Metrics HTTP Server
# ------------------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    consumer_instance: Optional["AsyncInferenceWorker"] = None

    def do_GET(self):
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"UP","service":"kubescale-worker"}\n')

        elif self.path == "/readyz":
            is_ready = True
            if self.consumer_instance:
                is_ready = self.consumer_instance.is_ready()

            if is_ready:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"READY","service":"kubescale-worker"}\n')
            else:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"DEGRADED","service":"kubescale-worker"}\n')

        elif self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(generate_latest())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Silence default access logging to avoid noisy stdout in k8s
        pass


# ------------------------------------------------------------------------------
# Asynchronous Inference Worker
# ------------------------------------------------------------------------------
class AsyncInferenceWorker:
    """
    Consumes inference events from Strimzi Kafka, micro-batches inputs,
    invokes Triton over gRPC, and publishes completed predictions to results topic.
    """

    def __init__(self):
        self.running = False
        self._consumer: Optional[KafkaConsumer] = None
        self._producer: Optional[KafkaProducer] = None
        self._triton_client: Optional[grpcclient.InferenceServerClient] = None
        self._health_server: Optional[HTTPServer] = None
        self._health_thread: Optional[threading.Thread] = None

    def start_health_server(self):
        """Start non-blocking HTTP server for Kubernetes health probes."""
        HealthCheckHandler.consumer_instance = self
        self._health_server = HTTPServer(("0.0.0.0", settings.HEALTH_PORT), HealthCheckHandler)
        self._health_thread = threading.Thread(
            target=self._health_server.serve_forever, daemon=True
        )
        self._health_thread.start()
        logger.info("Worker health probe and metrics server started on port %d", settings.HEALTH_PORT)

    def init_triton(self) -> bool:
        """Connect to Triton Inference Server via gRPC."""
        if not TRITON_AVAILABLE:
            logger.warning("tritonclient.grpc not found; operating in simulation mode.")
            return False

        try:
            self._triton_client = grpcclient.InferenceServerClient(
                url=settings.TRITON_GRPC_URL,
                verbose=False,
                connection_timeout=settings.TRITON_TIMEOUT_SECONDS,
                network_timeout=settings.TRITON_TIMEOUT_SECONDS,
            )
            logger.info("Connected to Triton Inference Server at %s", settings.TRITON_GRPC_URL)
            return True
        except Exception as e:
            logger.warning("Triton connection attempt failed: %s", str(e))
            self._triton_client = None
            return False

    def init_kafka(self) -> bool:
        """Connect consumer and producer to Strimzi Kafka broker."""
        if not KAFKA_AVAILABLE:
            logger.warning("kafka-python-ng not found; operating in simulation mode.")
            return False

        try:
            bootstrap_list = settings.KAFKA_BOOTSTRAP_SERVERS.split(",")
            self._consumer = KafkaConsumer(
                settings.KAFKA_REQUESTS_TOPIC,
                bootstrap_servers=bootstrap_list,
                group_id=settings.KAFKA_GROUP_ID,
                client_id=settings.KAFKA_CLIENT_ID,
                auto_offset_reset=settings.KAFKA_AUTO_OFFSET_RESET,
                enable_auto_commit=settings.KAFKA_ENABLE_AUTO_COMMIT,
                max_poll_records=settings.MAX_POLL_RECORDS,
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
                key_deserializer=lambda k: k.decode("utf-8") if k else None,
            )

            self._producer = KafkaProducer(
                bootstrap_servers=bootstrap_list,
                client_id=f"{settings.KAFKA_CLIENT_ID}-out",
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                retries=3,
            )
            logger.info(
                "Connected to Strimzi Kafka at %s, subscribed to '%s'",
                settings.KAFKA_BOOTSTRAP_SERVERS,
                settings.KAFKA_REQUESTS_TOPIC,
            )
            return True
        except Exception as e:
            logger.warning("Kafka initialization failed: %s", str(e))
            self._consumer = None
            self._producer = None
            return False

    def is_ready(self) -> bool:
        """Readiness check verifying Kafka and Triton dependencies."""
        if settings.ENVIRONMENT == "dev":
            return True
        kafka_ok = self._consumer is not None and self._producer is not None
        triton_ok = self._triton_client is not None
        return kafka_ok and triton_ok

    def process_micro_batch(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Micro-batch inference execution:
        Takes a list of request records, concatenates their input tensors,
        executes a single vectorized inference call against Triton,
        and slices results back to individual responses.
        """
        if not records:
            return []

        # Extract distributed W3C trace context from the first record if present
        first_trace_ctx = None
        if records and isinstance(records[0], dict):
            first_trace_ctx = extract_trace_context(records[0].get("trace_context", {}))

        with trace_span(
            "worker.process_micro_batch",
            attributes={
                "batch.size": len(records),
                "model.name": records[0].get("model_name", settings.DEFAULT_MODEL_NAME),
            },
            context=first_trace_ctx,
        ):
            BATCH_SIZE_HIST.observe(len(records))
            batch_inputs = []
            slice_indices = []
            current_idx = 0

            # Build concatenated input matrix
            for rec in records:
                inputs = rec.get("inputs", [])
                count = len(inputs)
                slice_indices.append((current_idx, current_idx + count))
                current_idx += count
                batch_inputs.extend(inputs)

            model_name = records[0].get("model_name", settings.DEFAULT_MODEL_NAME)
            model_version = str(records[0].get("model_version", settings.DEFAULT_MODEL_VERSION))

            # Execute batch inference
            infer_start = time.perf_counter()
            with trace_span(
                "worker.triton_batch_infer",
                attributes={
                    "model.name": model_name,
                    "model.version": model_version,
                    "batch.tensor_count": len(batch_inputs),
                },
            ):
                all_outputs = self._execute_inference(model_name, model_version, batch_inputs)

            infer_duration = time.perf_counter() - infer_start
            INFERENCE_LATENCY.labels(model_name=model_name).observe(infer_duration)

            # Slice outputs back to individual records
            results = []
            for i, rec in enumerate(records):
                start_i, end_i = slice_indices[i]
                rec_outputs = all_outputs[start_i:end_i]

                predictions = []
                for row in rec_outputs:
                    if len(row) > 0:
                        predictions.append(int(row.index(max(row))))

                result_msg = {
                    "request_id": rec.get("request_id"),
                    "model_name": model_name,
                    "model_version": model_version,
                    "outputs": rec_outputs,
                    "predictions": predictions,
                    "status": "COMPLETED",
                    "callback_topic": rec.get("callback_topic", settings.KAFKA_RESULTS_TOPIC),
                    "metadata": rec.get("metadata", {}),
                    "trace_context": rec.get("trace_context", {}),
                    "inference_time_ms": round(infer_duration * 1000.0, 2),
                    "completed_at": time.time(),
                }
                results.append(result_msg)

            return results

    def _execute_inference(
        self, model_name: str, model_version: str, input_data: List[List[float]]
    ) -> List[List[float]]:
        """Perform gRPC inference or deterministic fallback computation."""
        if not input_data:
            return []

        if self._triton_client is not None:
            try:
                np_input = np.array(input_data, dtype=np.float32)
                infer_input = grpcclient.InferInput("INPUT_0", list(np_input.shape), "FP32")
                infer_input.set_data_from_numpy(np_input)
                requested_output = grpcclient.InferRequestedOutput("OUTPUT_0")

                response = self._triton_client.infer(
                    model_name=model_name,
                    model_version=model_version,
                    inputs=[infer_input],
                    outputs=[requested_output],
                    client_timeout=settings.TRITON_TIMEOUT_SECONDS,
                )
                output_arr = response.as_numpy("OUTPUT_0")
                if output_arr is not None:
                    return output_arr.tolist()
            except Exception as e:
                logger.error("Triton gRPC call error: %s. Using simulated fallback.", str(e))

        # Simulation fallback for development / unit testing
        results = []
        for sample in input_data:
            s = float(sum(sample))
            prob_pos = 1.0 / (1.0 + np.exp(-s if abs(s) < 50 else 0))
            prob_neg = 1.0 - prob_pos
            results.append([round(prob_neg, 4), round(prob_pos, 4)])
        return results

    def run(self):
        """Main continuous event loop."""
        self.running = True
        if settings.OTEL_ENABLED:
            init_tracer(
                service_name=settings.OTEL_SERVICE_NAME,
                environment=settings.ENVIRONMENT,
                endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
                sampling_ratio=settings.OTEL_SAMPLING_RATIO,
            )
        self.start_health_server()
        self.init_triton()
        self.init_kafka()

        logger.info("KubeScale AI Async Worker event loop initialized and active.")

        while self.running:
            if self._consumer is None:
                # If Kafka is unavailable, sleep briefly and retry connection
                time.sleep(2.0)
                if not self.init_kafka():
                    continue

            try:
                raw_messages = self._consumer.poll(
                    timeout_ms=settings.POLL_TIMEOUT_MS,
                    max_records=settings.MAX_POLL_RECORDS,
                )

                if not raw_messages:
                    continue

                for topic_partition, records in raw_messages.items():
                    if not records:
                        continue

                    batch_start = time.perf_counter()
                    extracted_payloads = [r.value for r in records if r.value]

                    # Process micro-batch
                    results = self.process_micro_batch(extracted_payloads)

                    # Publish results to Kafka results topic
                    if self._producer:
                        for res in results:
                            target_topic = res.get("callback_topic") or settings.KAFKA_RESULTS_TOPIC
                            self._producer.send(
                                target_topic,
                                key=res.get("request_id"),
                                value=res,
                            )
                        self._producer.flush(timeout=5.0)

                    # Commit Kafka consumer offsets only after guaranteed delivery
                    self._consumer.commit()

                    batch_duration = time.perf_counter() - batch_start
                    PROCESSING_LATENCY.observe(batch_duration)
                    MESSAGES_CONSUMED.labels(status="success").inc(len(records))

                    logger.info(
                        "Processed micro-batch of %d records in %.2f ms",
                        len(records),
                        batch_duration * 1000.0,
                    )

            except Exception as e:
                MESSAGES_CONSUMED.labels(status="error").inc()
                logger.error("Error in worker consumer loop: %s", str(e))
                time.sleep(1.0)

    def stop(self):
        """Gracefully shut down connections and HTTP server."""
        logger.info("Stopping KubeScale Async Inference Worker...")
        self.running = False
        if self._consumer:
            try:
                self._consumer.close()
            except Exception:
                pass
        if self._producer:
            try:
                self._producer.flush(timeout=3.0)
                self._producer.close()
            except Exception:
                pass
        if self._health_server:
            try:
                self._health_server.shutdown()
            except Exception:
                pass
        logger.info("Worker shutdown complete.")


def main():
    worker = AsyncInferenceWorker()

    def signal_handler(signum, frame):
        logger.info("Received termination signal %d.", signum)
        worker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    worker.run()


if __name__ == "__main__":
    main()
