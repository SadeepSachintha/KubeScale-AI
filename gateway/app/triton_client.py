import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
import numpy as np

try:
    import tritonclient.grpc as grpcclient
    from tritonclient.utils import InferenceServerException
    TRITON_AVAILABLE = True
except ImportError:
    TRITON_AVAILABLE = False
    grpcclient = None
    InferenceServerException = Exception

from app.config import settings

logger = logging.getLogger(__name__)


class TritonGrpcClient:
    """
    High-performance gRPC client wrapper for Triton Inference Server.
    Encapsulates connection lifecycle, health probes, dynamic batching tensor preparation,
    and fallback handling for local development/unit testing.
    """

    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.TRITON_GRPC_URL
        self._client: Optional[grpcclient.InferenceServerClient] = None
        self._is_connected = False
        self._model_metadata_cache: Dict[str, dict] = {}

    def get_client(self) -> Optional[grpcclient.InferenceServerClient]:
        """Lazy-initialize or return existing Triton gRPC client instance."""
        if not TRITON_AVAILABLE:
            logger.warning("tritonclient.grpc not installed; operating in mock fallback mode.")
            return None

        if self._client is None:
            try:
                self._client = grpcclient.InferenceServerClient(
                    url=self.url,
                    verbose=False,
                    connection_timeout=settings.TRITON_TIMEOUT_SECONDS,
                    network_timeout=settings.TRITON_TIMEOUT_SECONDS,
                )
                self._is_connected = True
                logger.info("Initialized Triton gRPC client for endpoint: %s", self.url)
            except Exception as e:
                logger.error("Failed to initialize Triton gRPC client: %s", str(e))
                self._client = None
                self._is_connected = False

        return self._client

    def is_healthy(self) -> bool:
        """Probe Triton server live and ready status via gRPC."""
        client = self.get_client()
        if client is None:
            return False
        try:
            return client.is_server_live() and client.is_server_ready()
        except Exception as e:
            logger.debug("Triton health check failed: %s", str(e))
            return False

    def is_model_ready(self, model_name: str, model_version: str = "1") -> bool:
        """Verify if a specific model and version are loaded and ready in Triton."""
        client = self.get_client()
        if client is None:
            return False
        try:
            return client.is_model_ready(model_name=model_name, model_version=model_version)
        except Exception as e:
            logger.debug("Model %s ready check failed: %s", model_name, str(e))
            return False

    async def infer(
        self,
        model_name: str,
        input_data: List[List[float]],
        model_version: str = "1",
        input_tensor_name: str = "INPUT_0",
        output_tensor_name: str = "OUTPUT_0",
    ) -> Tuple[List[List[float]], float]:
        """
        Execute inference asynchronously using non-blocking thread execution
        to avoid GIL blocks in the FastAPI event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._infer_sync,
            model_name,
            input_data,
            model_version,
            input_tensor_name,
            output_tensor_name,
        )

    def _infer_sync(
        self,
        model_name: str,
        input_data: List[List[float]],
        model_version: str,
        input_tensor_name: str,
        output_tensor_name: str,
    ) -> Tuple[List[List[float]], float]:
        """
        Synchronous gRPC inference execution with numpy tensor serialization.
        """
        start_time = time.perf_counter()
        client = self.get_client()

        # If Triton is unreachable or running in mock development mode:
        if client is None or not self.is_healthy():
            logger.warning(
                "Triton is unreachable at %s. Executing deterministic fallback simulation.",
                self.url,
            )
            return self._mock_inference(input_data, start_time)

        try:
            # Prepare input numpy array (FP32)
            np_input = np.array(input_data, dtype=np.float32)

            infer_input = grpcclient.InferInput(
                name=input_tensor_name,
                shape=list(np_input.shape),
                datatype="FP32",
            )
            infer_input.set_data_from_numpy(np_input)

            requested_output = grpcclient.InferRequestedOutput(name=output_tensor_name)

            response = client.infer(
                model_name=model_name,
                model_version=model_version,
                inputs=[infer_input],
                outputs=[requested_output],
                client_timeout=settings.TRITON_TIMEOUT_SECONDS,
            )

            result_array = response.as_numpy(output_tensor_name)
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            if result_array is None:
                raise RuntimeError("Empty response received from Triton inference server")

            return result_array.tolist(), latency_ms

        except Exception as e:
            logger.error("gRPC inference failed for model '%s': %s", model_name, str(e))
            raise

    def _mock_inference(
        self, input_data: List[List[float]], start_time: float
    ) -> Tuple[List[List[float]], float]:
        """
        Simulated inference for local development and integration testing.
        Calculates a softmax-like probability distribution over 2 classes.
        """
        results = []
        for sample in input_data:
            s = float(sum(sample))
            # Sigmoid / Softmax simulation: [P(class_0), P(class_1)]
            prob_pos = 1.0 / (1.0 + np.exp(-s if abs(s) < 50 else 0))
            prob_neg = 1.0 - prob_pos
            results.append([round(prob_neg, 4), round(prob_pos, 4)])

        # Small simulated latency to model network call
        time.sleep(0.005)
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return results, latency_ms

    def close(self):
        """Close gRPC client connection channel."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._is_connected = False


# Global singleton instance
triton_client = TritonGrpcClient()
