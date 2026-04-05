"""Embedder adapter for neo4j-graphrag compatibility.

This module provides an adapter that wraps BaseEmbeddingGenerator
to make it compatible with the neo4j-graphrag embedder interface.
"""

from typing import TYPE_CHECKING, List

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models import EmbedderNotConfiguredError

if TYPE_CHECKING:
    from ...processing.embedding_generator import (
        EmbeddingGenerator as BaseEmbeddingGenerator,
    )

logger = EnhancedLogger(__name__)


class EmbedderAdapter:
    """Adapter to make BaseEmbeddingGenerator compatible with neo4j-graphrag.

    The neo4j-graphrag library expects an embedder with an `embed_query` method
    that takes a string and returns a list of floats. This adapter wraps our
    BaseEmbeddingGenerator to provide that interface.

    Attributes:
        _generator: The underlying BaseEmbeddingGenerator instance.
    """

    def __init__(self, embedding_generator: "BaseEmbeddingGenerator"):
        """Initialize the EmbedderAdapter.

        Args:
            embedding_generator: The BaseEmbeddingGenerator to wrap.

        Raises:
            EmbedderNotConfiguredError: If embedding_generator is None.
        """
        if embedding_generator is None:
            raise EmbedderNotConfiguredError(
                "Embedding generator is required for EmbedderAdapter"
            )
        self._generator = embedding_generator
        logger.debug(
            f"EmbedderAdapter initialized with {type(embedding_generator).__name__}"
        )

    @property
    def dimensions(self) -> int:
        """Get embedding dimensions from the underlying generator.

        Returns:
            The number of dimensions in the embedding vectors.
        """
        return self._generator.dimensions

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a query string.

        This method provides the interface expected by neo4j-graphrag.

        Args:
            text: The query text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            EmbedderNotConfiguredError: If the underlying generator fails.
            ValueError: If text is empty or invalid.
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")

        try:
            embedding = self._generator.embed(text)
            return embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise EmbedderNotConfiguredError(
                f"Failed to generate embedding: {e}"
            ) from e

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts.

        This method provides batch embedding capability for efficiency.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            EmbedderNotConfiguredError: If the underlying generator fails.
            ValueError: If texts list is empty or contains empty strings.
        """
        if not texts:
            raise ValueError("Cannot embed empty list of texts")

        try:
            embeddings = self._generator.embed_batch(texts)
            return embeddings
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")
            raise EmbedderNotConfiguredError(
                f"Failed to generate batch embeddings: {e}"
            ) from e
