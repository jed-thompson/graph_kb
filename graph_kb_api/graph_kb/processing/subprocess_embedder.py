"""Subprocess-based embedding generator for OOM isolation.

This module runs embedding generation in a separate subprocess to protect
the main application from OOM kills (exit code 137). If the subprocess
is killed by OOM, the parent process can handle it gracefully and resume.
"""

import multiprocessing
from dataclasses import dataclass
from multiprocessing import Process, Queue
from typing import List, Optional, Tuple

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


@dataclass
class EmbeddingTask:
    """A single embedding task to be processed."""

    chunk_id: str
    content: str
    file_node_id: str


@dataclass
class EmbeddingTaskResult:
    """Result of an embedding task."""

    chunk_id: str
    embedding: Optional[List[float]]
    error: Optional[str]
    success: bool


def _embedding_worker(
    task_queue: Queue,
    result_queue: Queue,
    model_name: str,
    device: Optional[str],
    stop_event: multiprocessing.Event,
):
    """Worker function that runs in subprocess to generate embeddings.

    This function is isolated in a subprocess so that if it gets OOM killed,
    the parent process survives.

    Args:
        task_queue: Queue to receive embedding tasks.
        result_queue: Queue to send results back.
        model_name: Name of the embedding model to use.
        device: Device to run on (cuda, mps, cpu, or None for auto).
        stop_event: Event to signal worker to stop.
    """
    import gc

    # Import inside subprocess to avoid loading model in parent
    try:
        from graph_kb_api.core.model_cache import get_cached_model

        logger.info(f"Subprocess worker starting, loading model: {model_name}")
        model = get_cached_model(model_name, device=device, trust_remote_code=True)
        logger.info(f"Model loaded in subprocess on device: {model.device}")

    except Exception as e:
        logger.error(f"Failed to load model in subprocess: {e}")
        # Signal error and exit
        result_queue.put({"type": "error", "message": f"Model load failed: {e}"})
        return

    # Signal ready
    result_queue.put({"type": "ready"})

    while not stop_event.is_set():
        try:
            # Get task with timeout to allow checking stop_event
            try:
                task_data = task_queue.get(timeout=1.0)
            except:
                continue

            if task_data is None:  # Poison pill
                break

            chunk_id = task_data["chunk_id"]
            content = task_data["content"]

            try:
                # Force GC before embedding
                gc.collect()

                # Generate embedding
                embedding = model.encode(content, convert_to_numpy=True).tolist()

                result_queue.put(
                    {
                        "type": "result",
                        "chunk_id": chunk_id,
                        "embedding": embedding,
                        "success": True,
                        "error": None,
                    }
                )

            except Exception as e:
                logger.error(f"Embedding failed for chunk {chunk_id}: {e}")
                result_queue.put(
                    {
                        "type": "result",
                        "chunk_id": chunk_id,
                        "embedding": None,
                        "success": False,
                        "error": str(e),
                    }
                )

            # GC after each embedding
            gc.collect()

        except Exception as e:
            logger.error(f"Worker error: {e}")
            continue

    logger.info("Subprocess worker shutting down")


class SubprocessEmbedder:
    """Manages embedding generation in an isolated subprocess.

    This class spawns a subprocess to run the embedding model, protecting
    the main application from OOM kills. If the subprocess dies, it can
    be restarted and embedding can resume.
    """

    def __init__(
        self,
        model_name: str,
        device: Optional[str] = None,
        timeout_per_chunk: float = 60.0,
    ):
        """Initialize the subprocess embedder.

        Args:
            model_name: Name of the embedding model.
            device: Device to run on.
            timeout_per_chunk: Timeout in seconds for each chunk.
        """
        self.model_name = model_name
        self.device = device
        self.timeout_per_chunk = timeout_per_chunk

        self._process: Optional[Process] = None
        self._task_queue: Optional[Queue] = None
        self._result_queue: Optional[Queue] = None
        self._stop_event: Optional[multiprocessing.Event] = None
        self._is_ready = False

    def start(self) -> bool:
        """Start the subprocess worker.

        Returns:
            True if started successfully, False otherwise.
        """
        if self._process is not None and self._process.is_alive():
            return True

        try:
            # Use 'spawn' to ensure clean subprocess (important for CUDA)
            ctx = multiprocessing.get_context("spawn")

            self._task_queue = ctx.Queue()
            self._result_queue = ctx.Queue()
            self._stop_event = ctx.Event()

            self._process = ctx.Process(
                target=_embedding_worker,
                args=(
                    self._task_queue,
                    self._result_queue,
                    self.model_name,
                    self.device,
                    self._stop_event,
                ),
                daemon=True,
            )
            self._process.start()

            # Wait for ready signal or error
            try:
                result = self._result_queue.get(
                    timeout=60.0
                )  # Model is pre-cached in Docker image, just loading from disk
                if result.get("type") == "ready":
                    self._is_ready = True
                    logger.info("Subprocess embedder ready")
                    return True
                elif result.get("type") == "error":
                    logger.error(f"Subprocess failed to start: {result.get('message')}")
                    self.stop()
                    return False
            except Exception as e:
                logger.error(f"Timeout waiting for subprocess: {e}")
                self.stop()
                return False

        except Exception as e:
            logger.error(f"Failed to start subprocess: {e}")
            return False

    def stop(self):
        """Stop the subprocess worker."""
        if self._stop_event:
            self._stop_event.set()

        if self._task_queue:
            try:
                self._task_queue.put(None)  # Poison pill
            except:
                pass

        if self._process:
            self._process.join(timeout=5.0)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2.0)
                if self._process.is_alive():
                    self._process.kill()

        self._process = None
        self._task_queue = None
        self._result_queue = None
        self._stop_event = None
        self._is_ready = False

    def is_alive(self) -> bool:
        """Check if the subprocess is alive."""
        return self._process is not None and self._process.is_alive()

    def embed_single(
        self, chunk_id: str, content: str
    ) -> Tuple[Optional[List[float]], Optional[str]]:
        """Embed a single chunk in the subprocess.

        Args:
            chunk_id: ID of the chunk.
            content: Text content to embed.

        Returns:
            Tuple of (embedding, error). If successful, error is None.
            If failed, embedding is None and error contains the message.
        """
        if not self.is_alive():
            if not self.start():
                return None, "Failed to start subprocess"

        try:
            # Send task
            self._task_queue.put(
                {
                    "chunk_id": chunk_id,
                    "content": content,
                }
            )

            # Wait for result
            try:
                result = self._result_queue.get(timeout=self.timeout_per_chunk)

                if result.get("type") == "result":
                    if result.get("success"):
                        return result.get("embedding"), None
                    else:
                        return None, result.get("error", "Unknown error")
                else:
                    return None, f"Unexpected result type: {result.get('type')}"

            except Exception as e:
                # Timeout or queue error - subprocess may have died
                if not self.is_alive():
                    exit_code = self._process.exitcode if self._process else None
                    if exit_code == -9 or exit_code == 137:
                        return None, "OOM: Subprocess killed by system (exit code 137)"
                    return None, f"Subprocess died with exit code {exit_code}"
                return None, f"Timeout waiting for embedding: {e}"

        except Exception as e:
            return None, f"Error sending task: {e}"

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
