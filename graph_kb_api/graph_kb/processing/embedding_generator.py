"""Embedding generation for code chunks.

This module handles generating vector embeddings for code chunks
using either OpenAI's embedding API or local models (Jina embeddings).
"""

import asyncio
import hashlib
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Tuple

import tiktoken
from openai import APIError, AsyncOpenAI, BadRequestError, OpenAI, RateLimitError
from sentence_transformers import SentenceTransformer

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

from ..models import BatchEmbeddingResult


class EmbeddingCache:
    """Thread-safe in-memory cache for embeddings."""

    def __init__(self, max_size: int = 10000):
        """Initialize the cache.

        Args:
            max_size: Maximum number of entries to cache.
        """
        self._cache: Dict[str, List[float]] = {}
        self._max_size = max_size
        self._lock = threading.Lock()

    def _hash_text(self, text: str) -> str:
        """Generate a hash key for text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[List[float]]:
        """Get cached embedding for text."""
        key = self._hash_text(text)
        with self._lock:
            return self._cache.get(key)

    def set(self, text: str, embedding: List[float]) -> None:
        """Cache an embedding for text."""
        key = self._hash_text(text)
        with self._lock:
            if len(self._cache) >= self._max_size:
                # Simple eviction: remove oldest entry
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key] = embedding

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        """Return number of cached entries."""
        with self._lock:
            return len(self._cache)


class EmbeddingGenerator(ABC):
    """Abstract base class for embedding generators.

    This interface defines the contract for generating vector embeddings
    from text content.
    """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Get embedding dimensions for the current model."""
        pass

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        pass

    @abstractmethod
    def embed_batch_soft(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Generate embeddings with soft error handling."""
        pass

    @abstractmethod
    async def embed_batch_concurrent(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[List[float]]:
        """Generate embeddings concurrently for multiple texts."""
        pass

    @abstractmethod
    async def embed_batch_soft_concurrent(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Generate embeddings concurrently with soft error handling."""
        pass

    @abstractmethod
    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        pass

    @property
    @abstractmethod
    def cache_size(self) -> int:
        """Get current cache size."""
        pass


class LocalEmbeddingGenerator(EmbeddingGenerator):
    """Generates vector embeddings using local embedding models.

    Supports multiple models with automatic dimension/token configuration:
    - nomic-ai/nomic-embed-code: Code-specialized, 768 dims, 8192 tokens
    - jinaai/jina-embeddings-v2-base-code: Code-specialized, 768 dims, 8192 tokens
    - all-MiniLM-L6-v2: Fast general-purpose, 384 dims, 512 tokens

    No API calls needed - runs locally on CPU/GPU/MPS.
    """

    DEFAULT_MODEL = "nomic-ai/nomic-embed-code"
    # Batch sizes per device type:
    # - CPU: batch_size=1 to prevent OOM (Jina v3 ~3.8GB + activations)
    # - GPU: batch_size=32, VRAM is much larger and GPU thrives on parallelism
    BATCH_SIZE_BY_DEVICE = {"cuda": 2, "mps": 1, "cpu": 1}
    MAX_BATCH_SIZE = 1  # Default, overridden after device resolution

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: Optional[str] = None,
        cache_enabled: bool = True,
        cache_size: int = 10000,
        trust_remote_code: bool = True,
    ):
        """Initialize the LocalEmbeddingGenerator.

        Note: Model is loaded lazily on first use to avoid OOM at startup.

        Args:
            model_name: HuggingFace model name for embeddings.
            device: Device to run model on ('cuda', 'mps', 'cpu', or None for auto).
            cache_enabled: Whether to cache embeddings.
            cache_size: Maximum cache size.
            trust_remote_code: Whether to trust remote code for model loading.
        """
        from graph_kb_api.config import (
            DEFAULT_EMBEDDING_CONFIG,
            EMBEDDING_MODEL_CONFIGS,
        )

        self.model_name = model_name
        # Disable cache for large models to save memory (Jina v3 is ~3.8GB)
        # Cache can accumulate and cause OOM during long ingestion runs
        if model_name in ("jinaai/jina-embeddings-v3", "nomic-ai/nomic-embed-code"):
            logger.info(
                f"Disabling embedding cache for large model {model_name} to prevent OOM"
            )
            self._cache = None
            self._cache_enabled = False
        else:
            self._cache = EmbeddingCache(max_size=cache_size) if cache_enabled else None
            self._cache_enabled = cache_enabled
        self._trust_remote_code = trust_remote_code

        # Get model config from centralized settings
        model_config = EMBEDDING_MODEL_CONFIGS.get(model_name, DEFAULT_EMBEDDING_CONFIG)
        self._embedding_dimensions = model_config["dimensions"]
        self._max_tokens = model_config["max_tokens"]

        if model_name not in EMBEDDING_MODEL_CONFIGS:
            logger.warning(
                f"Model '{model_name}' not found in config, using default: "
                f"{self._embedding_dimensions} dimensions, {self._max_tokens} max tokens"
            )
        else:
            logger.debug(
                f"Model config resolved: {model_name} -> {self._embedding_dimensions} dims, "
                f"{self._max_tokens} max tokens"
            )

        # Store device preference (will be resolved on first use)
        self._requested_device = device
        self._device: Optional[str] = None

        # Lazy-loaded model (loaded on first use to avoid OOM at startup)
        self.__model: Optional[SentenceTransformer] = None

        # Initialize tiktoken tokenizer for accurate token counting
        # Using cl100k_base encoding (same as chunker) for consistency
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

        logger.info(
            f"LocalEmbeddingGenerator initialized (lazy): {model_name} (model will load on first use)"
        )

    @property
    def _model(self) -> SentenceTransformer:
        """Lazy-load the model on first access using shared cache."""
        if self.__model is None:
            # Use shared model cache to avoid loading the same model multiple times
            from graph_kb_api.core.model_cache import get_cached_model

            logger.debug(
                f"Loading model: {self.model_name} (expected {self._embedding_dimensions} dimensions)"
            )

            self.__model = get_cached_model(
                self.model_name,
                device=self._requested_device,
                trust_remote_code=self._trust_remote_code,
            )

            # Update device to match what the cache resolved
            self._device = str(self.__model.device)
            actual_dims = self.__model.get_sentence_embedding_dimension()

            # Set batch size based on resolved device
            device_type = self._device.split(":")[0]  # "cuda:0" -> "cuda"
            self.MAX_BATCH_SIZE = self.BATCH_SIZE_BY_DEVICE.get(device_type, 1)
            logger.info(
                f"Batch size set to {self.MAX_BATCH_SIZE} for device '{device_type}'"
            )

            # Validate dimension consistency
            if actual_dims != self._embedding_dimensions:
                logger.warning(
                    f"Model dimension mismatch: model '{self.model_name}' produces {actual_dims} dimensions, "
                    f"but config expects {self._embedding_dimensions}. This may cause embedding validation errors."
                )
            else:
                logger.debug(
                    f"Model loaded successfully: {self.model_name} on {self._device}, "
                    f"{actual_dims} dimensions (matches config)"
                )

            logger.info(
                f"LocalEmbeddingGenerator using model: {self.model_name} | "
                f"dims={self._embedding_dimensions}, max_tokens={self._max_tokens}, device={self._device}"
            )
        return self.__model

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions for the current model."""
        return self._embedding_dimensions

    @property
    def max_tokens(self) -> int:
        """Get max tokens for the current model."""
        return self._max_tokens

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken.

        Args:
            text: Text to count tokens for.

        Returns:
            Number of tokens.
        """
        return len(self._tokenizer.encode(text))

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.

        Raises:
            ValueError: If text is empty.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        # Check cache
        if self._cache_enabled and self._cache:
            cached = self._cache.get(text)
            if cached is not None:
                return cached

        # Generate embedding
        embedding = self._model.encode(text, convert_to_numpy=True).tolist()

        # Cache result
        if self._cache_enabled and self._cache:
            self._cache.set(text, embedding)

        return embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            ValueError: If texts list is empty or contains empty strings.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        # Filter out empty texts and track indices
        valid_texts = []
        valid_indices = []
        cached_results: Dict[int, List[float]] = {}

        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise ValueError(f"Text at index {i} is empty")

            # Check cache
            if self._cache_enabled and self._cache:
                cached = self._cache.get(text)
                if cached is not None:
                    cached_results[i] = cached
                    continue

            valid_texts.append(text)
            valid_indices.append(i)

        # Generate embeddings for uncached texts
        if valid_texts:
            embeddings = self._model.encode(
                valid_texts,
                convert_to_numpy=True,
                batch_size=self.MAX_BATCH_SIZE,
                show_progress_bar=False,
            ).tolist()

            # Cache results
            if self._cache_enabled and self._cache:
                for text, embedding in zip(valid_texts, embeddings):
                    self._cache.set(text, embedding)

            # Merge with cached results
            for idx, embedding in zip(valid_indices, embeddings):
                cached_results[idx] = embedding

        # Return in original order
        return [cached_results[i] for i in range(len(texts))]

    def embed_batch_soft(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Generate embeddings with soft error handling.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            BatchEmbeddingResult with embeddings and failed indices.
        """
        result = BatchEmbeddingResult()

        if not texts:
            return result

        result.embeddings = [None] * len(texts)
        total_texts = len(texts)
        processed_count = 0

        # Filter out empty texts and check cache
        valid_texts = []
        valid_indices = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                result.failed_indices.append(i)
                result.errors[i] = "Empty text"
                processed_count += 1
                continue

            # Check cache
            if self._cache_enabled and self._cache:
                cached = self._cache.get(text)
                if cached is not None:
                    result.embeddings[i] = cached
                    processed_count += 1
                    continue

            valid_texts.append(text)
            valid_indices.append(i)

        if progress_callback and processed_count > 0:
            progress_callback(processed_count, total_texts)

        if not valid_texts:
            return result

        # Process in batches
        for batch_start in range(0, len(valid_texts), self.MAX_BATCH_SIZE):
            batch_end = min(batch_start + self.MAX_BATCH_SIZE, len(valid_texts))
            batch_texts = valid_texts[batch_start:batch_end]
            batch_indices = valid_indices[batch_start:batch_end]

            try:
                # Track memory during encoding to catch spikes
                def _get_memory_mb() -> int:
                    """Get current memory usage in MB with Docker fallback."""
                    try:
                        import psutil

                        process = psutil.Process()
                        return process.memory_info().rss // (1024 * 1024)
                    except ImportError:
                        # Fallback for Docker environments where psutil may not be available
                        try:
                            with open("/proc/self/status") as f:
                                for line in f:
                                    if line.startswith("VmRSS:"):
                                        return int(line.split()[1]) // 1024
                        except:
                            return -1
                    except:
                        # Try /proc fallback even if psutil import succeeds but fails at runtime
                        try:
                            with open("/proc/self/status") as f:
                                for line in f:
                                    if line.startswith("VmRSS:"):
                                        return int(line.split()[1]) // 1024
                        except:
                            return -1
                    return -1

                memory_before_encode = _get_memory_mb()
                # Only calculate headroom if memory tracking works
                headroom_before_encode = (
                    10000 - memory_before_encode
                    if memory_before_encode != -1
                    else 10000
                )

                # CRITICAL: Aggressive memory management before encoding to prevent OOM
                # PyTorch/SentenceTransformers can allocate large temporary buffers during encoding
                # For large chunks (>20KB), be extra aggressive with memory management
                max_chunk_size = max(len(t) for t in batch_texts) if batch_texts else 0
                is_large_chunk = max_chunk_size > 20000  # 20KB threshold
                # Use actual token count for accurate estimation
                estimated_tokens = (
                    max(self.count_tokens(t) for t in batch_texts) if batch_texts else 0
                )

                # Always do GC before encoding large chunks, or if headroom is low
                if memory_before_encode != -1 and (
                    headroom_before_encode < 4000 or is_large_chunk
                ):
                    logger.warning(
                        f"Low headroom ({headroom_before_encode}MB) or large chunk ({max_chunk_size} chars, ~{estimated_tokens} tokens). "
                        f"Clearing PyTorch cache and forcing GC."
                    )
                    import gc

                    import torch

                    gc.collect(2)  # Full GC
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    memory_after_cleanup = _get_memory_mb()
                    if memory_after_cleanup != -1:
                        logger.info(
                            f"After cleanup: {memory_before_encode}MB -> {memory_after_cleanup}MB "
                            f"(freed {memory_before_encode - memory_after_cleanup}MB)"
                        )
                        memory_before_encode = memory_after_cleanup
                        headroom_before_encode = 10000 - memory_before_encode

                # For very large chunks (>30KB), do additional aggressive cleanup
                # These chunks can cause memory spikes of 1-2GB during encoding
                if (
                    memory_before_encode != -1
                    and max_chunk_size > 30000
                    and headroom_before_encode < 6000
                ):
                    logger.warning(
                        f"Very large chunk ({max_chunk_size} chars, ~{estimated_tokens} tokens) with moderate headroom "
                        f"({headroom_before_encode}MB). Performing extra aggressive cleanup."
                    )
                    import gc

                    import torch

                    # Multiple GC passes for very large chunks
                    for _ in range(2):
                        gc.collect(2)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    memory_after_extra_cleanup = _get_memory_mb()
                    if memory_after_extra_cleanup != -1:
                        logger.info(
                            f"After extra cleanup: {memory_before_encode}MB -> {memory_after_extra_cleanup}MB "
                            f"(freed {memory_before_encode - memory_after_extra_cleanup}MB)"
                        )
                        memory_before_encode = memory_after_extra_cleanup
                        headroom_before_encode = 10000 - memory_before_encode

                # If memory tracking still doesn't work after cleanup, log warning
                if memory_before_encode == -1:
                    logger.warning(
                        f"Memory tracking unavailable during encoding. Large chunk size: {max_chunk_size} chars. "
                        f"Risk of undetected OOM spike."
                    )

                max_length = max(len(t) for t in batch_texts) if batch_texts else 0
                # Use actual token count for accurate logging
                estimated_tokens = (
                    max(self.count_tokens(t) for t in batch_texts) if batch_texts else 0
                )

                logger.info(
                    f"Encoding batch: {len(batch_texts)} texts, "
                    f"max_length={max_length} chars ({estimated_tokens} tokens), "
                    f"memory={memory_before_encode}MB, headroom={10000 - memory_before_encode if memory_before_encode != -1 else 'unknown'}MB"
                )

                # Note: Oversized chunks are now split at the indexer level before reaching here
                # This prevents OOM by ensuring all chunks fit within max_tokens
                # Let the model attempt to process - if it fails, we'll catch and log the error gracefully

                # CRITICAL: Final memory check before encoding - if headroom is critically low, skip to prevent OOM kill
                # OOM kills (exit code 137) happen at OS level and can't be caught by Python exception handlers
                # So we must prevent them proactively
                if memory_before_encode != -1 and headroom_before_encode < 2000:
                    error_msg = (
                        f"Critically low headroom ({headroom_before_encode}MB) before encoding. "
                        f"Skipping chunk ({max_length} chars, {estimated_tokens} tokens) to prevent OOM kill. "
                        f"Chunk will be marked as failed and can be retried later."
                    )
                    logger.error(error_msg)
                    # Mark all chunks in this batch as failed gracefully
                    for idx in batch_indices:
                        if idx not in result.failed_indices:
                            result.failed_indices.append(idx)
                            result.errors[idx] = (
                                f"Critically low headroom ({headroom_before_encode}MB) - skipped to prevent OOM"
                            )
                    processed_count += len(batch_texts)
                    if progress_callback:
                        progress_callback(processed_count, total_texts)
                    continue  # Skip encoding, move to next batch

                embeddings = self._model.encode(
                    batch_texts,
                    convert_to_numpy=True,
                    batch_size=self.MAX_BATCH_SIZE,
                    show_progress_bar=False,
                ).tolist()

                memory_after_encode = _get_memory_mb()
                encode_delta = memory_after_encode - memory_before_encode

                # Always log memory during encoding to catch spikes (use INFO level for visibility)
                logger.info(
                    f"Encoding memory: {memory_before_encode}MB -> {memory_after_encode}MB "
                    f"(+{encode_delta}MB) for {len(batch_texts)} texts"
                )
                if encode_delta > 200:  # More than 200MB spike during encoding
                    logger.warning(
                        f"Large memory spike during encode: +{encode_delta}MB for {len(batch_texts)} texts"
                    )

                for i, embedding in enumerate(embeddings):
                    original_idx = batch_indices[i]
                    result.embeddings[original_idx] = embedding

                    if self._cache_enabled and self._cache:
                        self._cache.set(batch_texts[i], embedding)

                # CRITICAL: Force GC after encoding to free PyTorch temporary buffers
                # This is especially important when processing expanded batches (e.g., 9 chunks)
                # PyTorch can accumulate memory across multiple encodes if not cleaned up
                import gc

                gc.collect(1)  # Quick GC to free temporary buffers

                processed_count += len(batch_texts)
                if progress_callback:
                    progress_callback(processed_count, total_texts)

            except Exception as e:
                # Log the error but don't crash - mark chunks as failed and continue processing
                error_msg = str(e)
                logger.error(
                    f"Batch embedding failed for {len(batch_texts)} chunk(s): {error_msg}. "
                    f"Chunks will be marked as failed and can be retried later."
                )
                # Mark all chunks in this batch as failed gracefully
                for idx in batch_indices:
                    if idx not in result.failed_indices:
                        result.failed_indices.append(idx)
                        result.errors[idx] = error_msg

                processed_count += len(batch_texts)
                if progress_callback:
                    progress_callback(processed_count, total_texts)

        return result

    async def embed_batch_concurrent(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[List[float]]:
        """Generate embeddings concurrently (runs sync in thread pool).

        For local models, we use asyncio.to_thread to avoid blocking the event loop.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            List of embedding vectors.
        """
        return await asyncio.to_thread(self.embed_batch, texts)

    async def embed_batch_soft_concurrent(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Generate embeddings concurrently with soft error handling.

        For local models, we use asyncio.to_thread to avoid blocking the event loop.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            BatchEmbeddingResult with embeddings and failed indices.
        """
        return await asyncio.to_thread(self.embed_batch_soft, texts, progress_callback)

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        if self._cache:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Get current cache size."""
        return len(self._cache) if self._cache else 0


class OpenAIEmbeddingGenerator(EmbeddingGenerator):
    """Generates vector embeddings for text using OpenAI API.

    This class provides functionality to:
    - Generate embeddings for single texts
    - Batch embed multiple texts efficiently
    - Cache embeddings to avoid redundant API calls
    - Handle rate limiting with exponential backoff
    """

    # Default embedding model
    DEFAULT_MODEL = "text-embedding-3-large"

    # Embedding dimensions by model
    MODEL_DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    # Rate limit retry settings
    MAX_RETRIES = 3
    BASE_DELAY = 1.0  # seconds
    MAX_DELAY = 60.0  # seconds

    # Default concurrent requests limit
    DEFAULT_MAX_CONCURRENT = 5

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        cache_enabled: bool = True,
        cache_size: int = 10000,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ):
        """Initialize the OpenAIEmbeddingGenerator.

        Args:
            model: OpenAI embedding model to use.
            api_key: OpenAI API key (uses OPENAI_API_KEY env var if not provided).
            cache_enabled: Whether to cache embeddings.
            cache_size: Maximum cache size.
            max_concurrent: Maximum concurrent API requests for async methods.
        """
        self.model = model
        self._client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self._async_client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()
        self._cache = EmbeddingCache(max_size=cache_size) if cache_enabled else None
        self._cache_enabled = cache_enabled
        self._max_concurrent = max_concurrent

        # Initialize tiktoken tokenizer for accurate token counting
        # Using cl100k_base encoding (OpenAI's encoding for GPT-4 and embedding models)
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions for the current model."""
        return self.MODEL_DIMENSIONS.get(self.model, 3072)

    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as list of floats.

        Raises:
            ValueError: If text is empty.
            APIError: If API call fails after retries.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        # Check cache
        if self._cache_enabled and self._cache:
            cached = self._cache.get(text)
            if cached is not None:
                logger.debug("Cache hit for embedding")
                return cached

        # Generate embedding with retry
        embedding = self._embed_with_retry([text])[0]

        # Cache result
        if self._cache_enabled and self._cache:
            self._cache.set(text, embedding)

        return embedding

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            ValueError: If texts list is empty or contains empty strings.
            APIError: If API call fails after retries.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        # Filter out empty texts and track indices
        valid_texts = []
        valid_indices = []
        cached_results: Dict[int, List[float]] = {}

        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise ValueError(f"Text at index {i} is empty")

            # Check cache
            if self._cache_enabled and self._cache:
                cached = self._cache.get(text)
                if cached is not None:
                    cached_results[i] = cached
                    continue

            valid_texts.append(text)
            valid_indices.append(i)

        # Generate embeddings for uncached texts
        if valid_texts:
            embeddings = self._embed_with_retry(valid_texts)

            # Cache results
            if self._cache_enabled and self._cache:
                for text, embedding in zip(valid_texts, embeddings):
                    self._cache.set(text, embedding)

            # Merge with cached results
            for idx, embedding in zip(valid_indices, embeddings):
                cached_results[idx] = embedding

        # Return in original order
        return [cached_results[i] for i in range(len(texts))]

    def embed_batch_soft(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Generate embeddings with soft error handling.

        Unlike embed_batch, this method does not fail on individual chunk errors.
        Instead, it tracks failed indices and continues processing remaining chunks.
        Failed chunks can be retried later.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count) for progress updates.

        Returns:
            BatchEmbeddingResult with embeddings and failed indices.
        """
        result = BatchEmbeddingResult()

        if not texts:
            return result

        # Initialize result embeddings with None placeholders
        result.embeddings = [None] * len(texts)
        total_texts = len(texts)
        processed_count = 0

        # Filter out empty texts and track indices
        valid_texts = []
        valid_indices = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                result.failed_indices.append(i)
                result.errors[i] = "Empty text"
                processed_count += 1
                continue

            # Check cache
            if self._cache_enabled and self._cache:
                cached = self._cache.get(text)
                if cached is not None:
                    result.embeddings[i] = cached
                    processed_count += 1
                    continue

            valid_texts.append(text)
            valid_indices.append(i)

        # Report initial progress (cached + empty texts already processed)
        if progress_callback and processed_count > 0:
            progress_callback(processed_count, total_texts)

        if not valid_texts:
            return result

        # Process in smaller sub-batches for better error isolation
        sub_batch_size = min(
            self.MAX_TEXTS_PER_BATCH, 50
        )  # Smaller batches for error isolation

        for batch_start in range(0, len(valid_texts), sub_batch_size):
            batch_end = min(batch_start + sub_batch_size, len(valid_texts))
            batch_texts = valid_texts[batch_start:batch_end]
            batch_indices = valid_indices[batch_start:batch_end]

            try:
                embeddings = self._embed_single_batch_with_fallback(
                    batch_texts, batch_indices, result
                )

                # Assign successful embeddings
                for i, embedding in enumerate(embeddings):
                    if embedding is not None:
                        original_idx = batch_indices[i]
                        result.embeddings[original_idx] = embedding

                        # Cache result
                        if self._cache_enabled and self._cache:
                            self._cache.set(batch_texts[i], embedding)

                # Update progress after each batch
                processed_count += len(batch_texts)
                if progress_callback:
                    progress_callback(processed_count, total_texts)

            except Exception as e:
                # Entire batch failed - mark all as failed
                logger.error(
                    f"Batch embedding failed for {len(batch_texts)} texts: {e}"
                )
                for idx in batch_indices:
                    if idx not in result.failed_indices:
                        result.failed_indices.append(idx)
                        result.errors[idx] = str(e)

                # Still update progress even on failure
                processed_count += len(batch_texts)
                if progress_callback:
                    progress_callback(processed_count, total_texts)

        return result

    def _embed_single_batch_with_fallback(
        self,
        texts: List[str],
        indices: List[int],
        result: BatchEmbeddingResult,
    ) -> List[Optional[List[float]]]:
        """Embed a single batch with fallback to individual processing on failure.

        If batch embedding fails due to token limits, falls back to processing
        texts individually to isolate the problematic ones.

        Args:
            texts: Texts to embed.
            indices: Original indices of these texts.
            result: BatchEmbeddingResult to update with failures.

        Returns:
            List of embeddings (None for failed ones).
        """
        try:
            # Try batch embedding first
            return self._embed_batch_direct(texts)
        except BadRequestError as e:
            # Token limit exceeded - fall back to individual processing
            if "maximum context length" in str(e).lower():
                logger.warning(
                    f"Batch exceeded token limit, falling back to individual processing "
                    f"for {len(texts)} texts"
                )
                return self._embed_individually(texts, indices, result)
            raise
        except APIError as e:
            # Other API errors - try individual processing
            logger.warning(f"Batch API error, trying individual processing: {e}")
            return self._embed_individually(texts, indices, result)

    def _embed_batch_direct(self, texts: List[str]) -> List[List[float]]:
        """Directly embed a batch without splitting.

        Args:
            texts: Texts to embed (should already be within size limits).

        Returns:
            List of embeddings.
        """
        # Truncate texts that exceed per-text limit
        processed_texts = [self._truncate_text(text) for text in texts]

        delay = self.BASE_DELAY
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.embeddings.create(
                    model=self.model,
                    input=processed_texts,
                )
                return [item.embedding for item in response.data]
            except RateLimitError:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                logger.warning(f"Rate limit hit, retrying in {delay:.1f}s")
                time.sleep(delay)
                delay = min(delay * 2, self.MAX_DELAY)

        raise APIError("Failed to generate embeddings after retries")

    def _embed_individually(
        self,
        texts: List[str],
        indices: List[int],
        result: BatchEmbeddingResult,
    ) -> List[Optional[List[float]]]:
        """Embed texts one by one to isolate failures.

        Args:
            texts: Texts to embed.
            indices: Original indices of these texts.
            result: BatchEmbeddingResult to update with failures.

        Returns:
            List of embeddings (None for failed ones).
        """
        embeddings: List[Optional[List[float]]] = []

        for i, text in enumerate(texts):
            original_idx = indices[i]
            try:
                truncated = self._truncate_text(text)
                response = self._client.embeddings.create(
                    model=self.model,
                    input=[truncated],
                )
                embeddings.append(response.data[0].embedding)
            except Exception as e:
                logger.warning(f"Failed to embed text at index {original_idx}: {e}")
                embeddings.append(None)
                result.failed_indices.append(original_idx)
                result.errors[original_idx] = str(e)

        return embeddings

    # Token limit per individual text for OpenAI embedding API
    MAX_TOKENS_PER_TEXT = 8191  # OpenAI limit is 8192, use 8191 for safety
    # Maximum number of texts per batch request (OpenAI allows up to 2048)
    MAX_TEXTS_PER_BATCH = 100  # Use smaller batches for reliability

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken.

        Args:
            text: Text to count tokens for.

        Returns:
            Number of tokens.
        """
        return len(self._tokenizer.encode(text))

    def _truncate_text(self, text: str) -> str:
        """Truncate text to fit within token limits.

        Uses actual token counting to ensure accurate truncation.

        Args:
            text: Text to truncate.

        Returns:
            Truncated text that fits within MAX_TOKENS_PER_TEXT.
        """
        token_count = self.count_tokens(text)
        if token_count <= self.MAX_TOKENS_PER_TEXT:
            return text

        # Truncate by tokens, then decode back to text
        tokens = self._tokenizer.encode(text)
        truncated_tokens = tokens[: self.MAX_TOKENS_PER_TEXT]
        truncated_text = self._tokenizer.decode(truncated_tokens)

        logger.warning(
            f"Text with {token_count} tokens exceeds limit ({self.MAX_TOKENS_PER_TEXT}), "
            f"truncating to {self.MAX_TOKENS_PER_TEXT} tokens"
        )
        return truncated_text

    def _split_into_token_batches(self, texts: List[str]) -> List[List[str]]:
        """Split texts into batches that fit within API limits.

        Each text is truncated if it exceeds the per-text token limit,
        and texts are grouped into batches of MAX_TEXTS_PER_BATCH.

        Args:
            texts: List of texts to split into batches.

        Returns:
            List of batches, where each batch fits within API limits.
        """
        # First, truncate any texts that exceed the per-text limit
        processed_texts = [self._truncate_text(text) for text in texts]

        # Split into batches by count
        batches = []
        for i in range(0, len(processed_texts), self.MAX_TEXTS_PER_BATCH):
            batch = processed_texts[i : i + self.MAX_TEXTS_PER_BATCH]
            batches.append(batch)

        return batches

    def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings with retry logic for rate limits.

        Automatically splits large batches to stay within API token limits.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            APIError: If API call fails after all retries.
        """
        # Split into token-safe batches
        batches = self._split_into_token_batches(texts)

        if len(batches) > 1:
            logger.info(
                f"Split {len(texts)} texts into {len(batches)} batches for embedding"
            )

        all_embeddings = []

        for batch_idx, batch in enumerate(batches):
            delay = self.BASE_DELAY

            for attempt in range(self.MAX_RETRIES):
                try:
                    response = self._client.embeddings.create(
                        model=self.model,
                        input=batch,
                    )
                    all_embeddings.extend([item.embedding for item in response.data])

                    if len(batches) > 1:
                        logger.debug(f"Completed batch {batch_idx + 1}/{len(batches)}")
                    break

                except RateLimitError:
                    if attempt == self.MAX_RETRIES - 1:
                        logger.error(
                            f"Rate limit exceeded after {self.MAX_RETRIES} retries"
                        )
                        raise

                    logger.warning(
                        f"Rate limit hit, retrying in {delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, self.MAX_DELAY)

                except APIError as e:
                    logger.error(f"API error: {e}")
                    raise
            else:
                # Loop completed without break - should not happen
                raise APIError("Failed to generate embeddings")

        return all_embeddings

    # -------------------------------------------------------------------------
    # Async Concurrent Embedding Methods
    # -------------------------------------------------------------------------

    async def _embed_batch_async(self, texts: List[str]) -> List[List[float]]:
        """Embed a single batch asynchronously using AsyncOpenAI client.

        Args:
            texts: Texts to embed (should already be within size limits).

        Returns:
            List of embeddings.

        Raises:
            APIError: If API call fails after retries.
        """
        processed_texts = [self._truncate_text(text) for text in texts]

        delay = self.BASE_DELAY
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._async_client.embeddings.create(
                    model=self.model,
                    input=processed_texts,
                )
                return [item.embedding for item in response.data]
            except RateLimitError:
                if attempt == self.MAX_RETRIES - 1:
                    raise
                logger.warning(f"Rate limit hit, retrying in {delay:.1f}s (async)")
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.MAX_DELAY)

        raise APIError("Failed to generate embeddings after retries")

    async def _embed_batches_concurrent(
        self,
        batches: List[List[str]],
        batch_indices: List[List[int]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        total_texts: int = 0,
    ) -> Tuple[List[List[float]], Dict[int, str]]:
        """Process multiple batches concurrently with semaphore control.

        Args:
            batches: List of text batches to embed.
            batch_indices: Original indices for each text in each batch.
            progress_callback: Optional callback(processed_count, total_count).
            total_texts: Total number of texts being processed.

        Returns:
            Tuple of (all_embeddings, errors_dict) where errors_dict maps
            original index to error message for failed texts.
        """
        semaphore = asyncio.Semaphore(self._max_concurrent)
        all_embeddings: List[Optional[List[float]]] = [None] * total_texts
        errors: Dict[int, str] = {}
        processed_count = [0]  # Use list for mutable reference in closure
        lock = asyncio.Lock()

        async def process_batch(batch_idx: int) -> None:
            """Process a single batch with semaphore control."""
            batch = batches[batch_idx]
            indices = batch_indices[batch_idx]

            async with semaphore:
                try:
                    embeddings = await self._embed_batch_async(batch)

                    async with lock:
                        for i, embedding in enumerate(embeddings):
                            original_idx = indices[i]
                            all_embeddings[original_idx] = embedding

                        processed_count[0] += len(batch)
                        if progress_callback:
                            progress_callback(processed_count[0], total_texts)

                except Exception as e:
                    logger.error(f"Batch {batch_idx} failed: {e}")
                    async with lock:
                        for idx in indices:
                            errors[idx] = str(e)
                        processed_count[0] += len(batch)
                        if progress_callback:
                            progress_callback(processed_count[0], total_texts)

        # Create tasks for all batches
        tasks = [process_batch(i) for i in range(len(batches))]
        await asyncio.gather(*tasks)

        return all_embeddings, errors

    async def embed_batch_concurrent(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[List[float]]:
        """Generate embeddings concurrently for multiple texts.

        Uses AsyncOpenAI client with semaphore-controlled concurrency to
        process multiple batches in parallel while respecting rate limits.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            List of embedding vectors.

        Raises:
            ValueError: If texts list is empty or contains empty strings.
            APIError: If API call fails after retries.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        # Filter out empty texts and check cache
        valid_texts = []
        valid_indices = []
        cached_results: Dict[int, List[float]] = {}

        for i, text in enumerate(texts):
            if not text or not text.strip():
                raise ValueError(f"Text at index {i} is empty")

            if self._cache_enabled and self._cache:
                cached = self._cache.get(text)
                if cached is not None:
                    cached_results[i] = cached
                    continue

            valid_texts.append(text)
            valid_indices.append(i)

        if not valid_texts:
            return [cached_results[i] for i in range(len(texts))]

        # Split into batches
        batches: List[List[str]] = []
        batch_indices: List[List[int]] = []

        for batch_start in range(0, len(valid_texts), self.MAX_TEXTS_PER_BATCH):
            batch_end = min(batch_start + self.MAX_TEXTS_PER_BATCH, len(valid_texts))
            batches.append(
                [self._truncate_text(t) for t in valid_texts[batch_start:batch_end]]
            )
            batch_indices.append(valid_indices[batch_start:batch_end])

        logger.info(
            f"Processing {len(valid_texts)} texts in {len(batches)} batches with max {self._max_concurrent} concurrent requests"
        )

        # Process batches concurrently
        embeddings, errors = await self._embed_batches_concurrent(
            batches=batches,
            batch_indices=batch_indices,
            progress_callback=progress_callback,
            total_texts=len(valid_texts),
        )

        if errors:
            # Some batches failed - raise error with details
            failed_count = len(errors)
            raise APIError(
                f"Failed to embed {failed_count} texts: {list(errors.values())[:3]}"
            )

        # Cache successful results
        if self._cache_enabled and self._cache:
            for i, idx in enumerate(valid_indices):
                if embeddings[idx] is not None:
                    self._cache.set(valid_texts[i], embeddings[idx])

        # Merge with cached results
        for idx, embedding in enumerate(embeddings):
            if embedding is not None:
                cached_results[
                    valid_indices[valid_indices.index(idx)]
                    if idx in valid_indices
                    else idx
                ] = embedding

        # Build final result in original order
        result = []
        for i in range(len(texts)):
            if i in cached_results:
                result.append(cached_results[i])
            elif embeddings[i] is not None:
                result.append(embeddings[i])
            else:
                raise APIError(f"Missing embedding for index {i}")

        return result

    async def embed_batch_soft_concurrent(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Generate embeddings concurrently with soft error handling.

        Unlike embed_batch_concurrent, this method does not fail on individual
        chunk errors. Instead, it tracks failed indices and continues processing.

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            BatchEmbeddingResult with embeddings and failed indices.
        """
        result = BatchEmbeddingResult()

        if not texts:
            return result

        result.embeddings = [None] * len(texts)
        total_texts = len(texts)
        processed_count = [0]

        # Filter out empty texts and check cache
        valid_texts = []
        valid_indices = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                result.failed_indices.append(i)
                result.errors[i] = "Empty text"
                processed_count[0] += 1
                continue

            if self._cache_enabled and self._cache:
                cached = self._cache.get(text)
                if cached is not None:
                    result.embeddings[i] = cached
                    processed_count[0] += 1
                    continue

            valid_texts.append(text)
            valid_indices.append(i)

        if progress_callback and processed_count[0] > 0:
            progress_callback(processed_count[0], total_texts)

        if not valid_texts:
            return result

        # Split into batches
        batches: List[List[str]] = []
        batch_indices: List[List[int]] = []

        for batch_start in range(0, len(valid_texts), self.MAX_TEXTS_PER_BATCH):
            batch_end = min(batch_start + self.MAX_TEXTS_PER_BATCH, len(valid_texts))
            batches.append(
                [self._truncate_text(t) for t in valid_texts[batch_start:batch_end]]
            )
            batch_indices.append(valid_indices[batch_start:batch_end])

        logger.info(
            f"Processing {len(valid_texts)} texts in {len(batches)} batches "
            f"with max {self._max_concurrent} concurrent requests (soft mode)"
        )

        # Wrap progress callback to account for already-processed items
        def adjusted_callback(batch_processed: int, batch_total: int) -> None:
            if progress_callback:
                progress_callback(processed_count[0] + batch_processed, total_texts)

        # Process batches concurrently
        embeddings, errors = await self._embed_batches_concurrent(
            batches=batches,
            batch_indices=batch_indices,
            progress_callback=adjusted_callback,
            total_texts=len(valid_texts),
        )

        # Assign results
        for i, idx in enumerate(valid_indices):
            if idx in errors:
                result.failed_indices.append(idx)
                result.errors[idx] = errors[idx]
            elif embeddings[idx] is not None:
                result.embeddings[idx] = embeddings[idx]
                # Cache successful result
                if self._cache_enabled and self._cache:
                    self._cache.set(valid_texts[i], embeddings[idx])
            else:
                result.failed_indices.append(idx)
                result.errors[idx] = "No embedding returned"

        return result

    def embed_batch_concurrent_sync(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[List[float]]:
        """Sync wrapper for concurrent embedding (for non-async callers).

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            List of embedding vectors.
        """
        return asyncio.run(self.embed_batch_concurrent(texts, progress_callback))

    def embed_batch_soft_concurrent_sync(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BatchEmbeddingResult:
        """Sync wrapper for concurrent soft embedding (for non-async callers).

        Args:
            texts: List of texts to embed.
            progress_callback: Optional callback(processed_count, total_count).

        Returns:
            BatchEmbeddingResult with embeddings and failed indices.
        """
        return asyncio.run(self.embed_batch_soft_concurrent(texts, progress_callback))

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        if self._cache:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        """Get current cache size."""
        return len(self._cache) if self._cache else 0
