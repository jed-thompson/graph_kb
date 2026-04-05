"""Embedding-related data models."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class EmbeddingResult:
    """Result of embedding generation."""

    embedding: List[float]
    model: str
    tokens_used: int


@dataclass
class BatchEmbeddingResult:
    """Result of batch embedding with soft error handling.

    Tracks successful embeddings and failed indices for retry.
    """
    embeddings: List[Optional[List[float]]] = field(default_factory=list)
    failed_indices: List[int] = field(default_factory=list)
    errors: Dict[int, str] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        """Number of successfully embedded texts."""
        return len(self.embeddings) - len(self.failed_indices)

    @property
    def failure_count(self) -> int:
        """Number of failed embeddings."""
        return len(self.failed_indices)

    @property
    def has_failures(self) -> bool:
        """Check if any embeddings failed."""
        return len(self.failed_indices) > 0

    @property
    def all_succeeded(self) -> bool:
        """Check if all embeddings succeeded."""
        return len(self.failed_indices) == 0
