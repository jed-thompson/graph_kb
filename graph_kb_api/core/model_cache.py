"""Global model cache for sharing expensive model instances across services.

This module provides a singleton cache for embedding models to avoid loading
the same model multiple times (which is expensive in terms of memory and time).

Models are expected to be pre-downloaded into the HF cache during Docker image
build. SentenceTransformer will find them locally and skip re-downloading.
"""

import threading
from typing import Dict, Optional

import torch
from sentence_transformers import SentenceTransformer

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class ModelCache:
    """Thread-safe singleton cache for embedding models.

    Ensures that expensive models like Jina embeddings are only loaded once
    and shared across all services (EmbeddingService, LocalEmbeddingGenerator, etc.).
    """

    _instance: Optional["ModelCache"] = None
    _lock = threading.Lock()
    _models: Dict[str, SentenceTransformer]
    _model_lock: threading.Lock

    def __new__(cls) -> "ModelCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._models = {}
                    cls._instance._model_lock = threading.Lock()
        return cls._instance

    def get_model(
        self,
        model_name: str,
        device: Optional[str] = None,
        trust_remote_code: bool = True,
    ) -> SentenceTransformer:
        """Get or load a model from the cache.

        Args:
            model_name: HuggingFace model name or path.
            device: Device to run model on ('cuda', 'mps', 'cpu', or None for auto).
            trust_remote_code: Whether to trust remote code for model loading.

        Returns:
            Loaded SentenceTransformer model.
        """
        # Create cache key based on model name and device
        actual_device = self._resolve_device(device)
        cache_key = f"{model_name}@{actual_device}"

        # Check if model is already cached
        if cache_key in self._models:
            logger.debug(f"Model cache hit: {cache_key}")
            return self._models[cache_key]

        # Load model with lock to prevent concurrent loading
        with self._model_lock:
            # Double-check after acquiring lock
            if cache_key in self._models:
                return self._models[cache_key]

            logger.info(f"Loading model into cache: {model_name} on {actual_device}")

            model = SentenceTransformer(
                model_name,
                device=actual_device,
                trust_remote_code=trust_remote_code,
            )

            self._models[cache_key] = model
            logger.info(f"Model cached: {cache_key}")

            return model

    def _resolve_device(self, requested_device: Optional[str]) -> str:
        """Resolve the best available device.

        Args:
            requested_device: Explicitly requested device, or None for auto-detection.

        Returns:
            Device string: "cuda", "mps", or "cpu"
        """
        if requested_device:
            # Validate requested device
            if requested_device == "cuda" and torch.cuda.is_available():
                return "cuda"
            elif requested_device == "mps":
                if torch.backends.mps.is_available() and torch.backends.mps.is_built():
                    try:
                        torch.zeros(1).to("mps")
                        return "mps"
                    except Exception:
                        logger.warning(
                            "MPS requested but not functional, falling back to CPU"
                        )
                        return "cpu"
                else:
                    logger.warning(
                        "MPS requested but not available, falling back to CPU"
                    )
                    return "cpu"
            elif requested_device == "cpu":
                return "cpu"
            else:
                logger.warning(
                    f"Unknown device '{requested_device}', falling back to CPU"
                )
                return "cpu"

        # Auto-detect best available device
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            logger.info(f"CUDA GPU detected: {gpu_name} ({gpu_mem:.1f} GB)")
            return "cuda"

        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            try:
                torch.zeros(1).to("mps")
                return "mps"
            except Exception:
                logger.warning(
                    "MPS detected but not functional (likely in Docker), using CPU"
                )
                return "cpu"

        return "cpu"

    def clear(self) -> None:
        """Clear all cached models."""
        with self._model_lock:
            self._models.clear()
            logger.info("Model cache cleared")

    def get_cached_models(self) -> list:
        """Get list of currently cached model keys."""
        return list(self._models.keys())


# Global singleton instance
_model_cache = ModelCache()


def get_cached_model(
    model_name: str,
    device: Optional[str] = None,
    trust_remote_code: bool = True,
) -> SentenceTransformer:
    """Convenience function to get a model from the global cache.

    Args:
        model_name: HuggingFace model name or path.
        device: Device to run model on ('cuda', 'mps', 'cpu', or None for auto).
        trust_remote_code: Whether to trust remote code for model loading.

    Returns:
        Loaded SentenceTransformer model.
    """
    return _model_cache.get_model(model_name, device, trust_remote_code)


def clear_model_cache() -> None:
    """Clear the global model cache."""
    _model_cache.clear()
