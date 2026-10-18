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
        # In-memory mock repository state for offline/testing/dev modes
        self._mock_repository: Dict[str, Dict[str, Any]] = {
            "sentiment_onnx": {
                "version": "1",
                "state": "READY",
                "reason": "",
                "platform": "onnxruntime_onnx",
                "inputs": [{"name": "INPUT_0", "datatype": "FP32", "shape": [-1, 128]}],
                "outputs": [{"name": "OUTPUT_0", "datatype": "FP32", "shape": [-1, 2]}],
            },
            "fraud_detection_onnx": {
                "version": "1",
                "state": "UNAVAILABLE",  # Not loaded initially; ready to be loaded via explicit control!
                "reason": "Explicit control mode - model unallocated",
                "platform": "onnxruntime_onnx",
                "inputs": [{"name": "INPUT_0", "datatype": "FP32", "shape": [-1, 64]}],
                "outputs": [{"name": "OUTPUT_0", "datatype": "FP32", "shape": [-1, 2]}],
            },
        }

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
        if client is not None and self.is_healthy():
            try:
                return client.is_model_ready(model_name=model_name, model_version=model_version)
            except Exception as e:
                logger.debug("Model %s ready check failed: %s", model_name, str(e))
                return False

        # Fallback simulation check against mock repository
        model_info = self._mock_repository.get(model_name)
        if not model_info:
            return False
        return model_info.get("state") == "READY"

    def get_model_repository_index(self) -> List[Dict[str, Any]]:
        """
        Query Triton model repository index to inspect loaded and available models.
        """
        client = self.get_client()
        if client is not None and self.is_healthy():
            try:
                res = client.get_model_repository_index()
                results = []
                for m in getattr(res, "models", []):
                    results.append({
                        "name": m.name,
                        "version": getattr(m, "version", "1"),
                        "state": getattr(m, "state", "READY"),
                        "reason": getattr(m, "reason", ""),
                    })
                return results
            except Exception as e:
                logger.error("Failed to query Triton model repository index: %s", str(e))
                raise

        # Mock fallback simulation
        return [
            {
                "name": name,
                "version": meta.get("version", "1"),
                "state": meta.get("state", "READY"),
                "reason": meta.get("reason", ""),
            }
            for name, meta in self._mock_repository.items()
        ]

    def load_model(self, model_name: str) -> Dict[str, Any]:
        """
        Dynamically load a model into Triton runtime memory without restarting the cluster.
        """
        client = self.get_client()
        if client is not None and self.is_healthy():
            try:
                client.load_model(model_name=model_name)
                logger.info("Successfully loaded model '%s' via Triton Model Control API", model_name)
                return {
                    "model_name": model_name,
                    "action": "LOAD",
                    "status": "SUCCESS",
                    "message": f"Model '{model_name}' successfully loaded into Triton runtime.",
                }
            except Exception as e:
                logger.error("Failed to load model '%s' via Triton gRPC: %s", model_name, str(e))
                raise

        # Mock fallback simulation
        if model_name in self._mock_repository:
            self._mock_repository[model_name]["state"] = "READY"
            self._mock_repository[model_name]["reason"] = ""
        else:
            self._mock_repository[model_name] = {
                "version": "1",
                "state": "READY",
                "reason": "",
                "platform": "onnxruntime_onnx",
                "inputs": [{"name": "INPUT_0", "datatype": "FP32", "shape": [-1, 64]}],
                "outputs": [{"name": "OUTPUT_0", "datatype": "FP32", "shape": [-1, 2]}],
            }
        return {
            "model_name": model_name,
            "action": "LOAD",
            "status": "SUCCESS",
            "message": f"Model '{model_name}' successfully loaded into Triton runtime (dynamic reload).",
        }

    def unload_model(self, model_name: str) -> Dict[str, Any]:
        """
        Dynamically unload a model from Triton runtime memory to reclaim GPU/CPU resources.
        """
        client = self.get_client()
        if client is not None and self.is_healthy():
            try:
                client.unload_model(model_name=model_name)
                logger.info("Successfully unloaded model '%s' via Triton Model Control API", model_name)
                return {
                    "model_name": model_name,
                    "action": "UNLOAD",
                    "status": "SUCCESS",
                    "message": f"Model '{model_name}' successfully unloaded from Triton runtime.",
                }
            except Exception as e:
                logger.error("Failed to unload model '%s' via Triton gRPC: %s", model_name, str(e))
                raise

        # Mock fallback simulation
        if model_name not in self._mock_repository:
            raise KeyError(f"Model '{model_name}' does not exist in Triton repository.")
        self._mock_repository[model_name]["state"] = "UNAVAILABLE"
        self._mock_repository[model_name]["reason"] = "Model unloaded via Model Control API"
        return {
            "model_name": model_name,
            "action": "UNLOAD",
            "status": "SUCCESS",
            "message": f"Model '{model_name}' successfully unloaded from Triton runtime.",
        }

    def get_model_metadata(self, model_name: str, model_version: str = "1") -> Dict[str, Any]:
        """
        Fetch input/output tensor specifications and platform metadata for a loaded model.
        """
        client = self.get_client()
        if client is not None and self.is_healthy():
            try:
                meta = client.get_model_metadata(model_name=model_name, model_version=model_version)
                inputs = [{"name": i.name, "datatype": i.datatype, "shape": list(i.shape)} for i in meta.inputs]
                outputs = [{"name": o.name, "datatype": o.datatype, "shape": list(o.shape)} for o in meta.outputs]
                return {
                    "name": meta.name,
                    "versions": list(meta.versions) if hasattr(meta, "versions") else [model_version],
                    "platform": getattr(meta, "platform", "onnxruntime_onnx"),
                    "inputs": inputs,
                    "outputs": outputs,
                }
            except Exception as e:
                logger.error("Failed to fetch metadata for model '%s': %s", model_name, str(e))
                raise

        # Mock fallback simulation
        if model_name not in self._mock_repository:
            raise KeyError(f"Model '{model_name}' not found in Triton repository.")
        entry = self._mock_repository[model_name]
        if entry.get("state") != "READY":
            raise RuntimeError(f"Model '{model_name}' is not ready in Triton runtime (state: {entry.get('state')}).")
        return {
            "name": model_name,
            "versions": [entry.get("version", "1")],
            "platform": entry.get("platform", "onnxruntime_onnx"),
            "inputs": entry.get("inputs", []),
            "outputs": entry.get("outputs", []),
        }

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
            if not self.is_model_ready(model_name, model_version):
                raise RuntimeError(
                    f"Model '{model_name}' (version {model_version}) is UNAVAILABLE or not loaded in Triton runtime. "
                    f"Load it first using POST /v1/repository/models/{model_name}/load"
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
