"""Storage layer components for graph, vector, and metadata stores."""

# MetadataStore is deprecated — use graph_kb_api.database.metadata_service instead.
# Re-export SyncMetadataService as MetadataStore for backward compatibility
# during the transition period.
from graph_kb_api.database.metadata_service import SyncMetadataService as MetadataStore

from .graph_store import (
    ArchitectureOverview,
    Neo4jGraphStore,
    VectorIndexNotAvailableError,
    VectorSearchResult,
)
from .interfaces import IGraphStore
from .vector_store import ChromaVectorStore, SearchResult


class MetadataStoreError(Exception):
    """Raised on metadata store failures."""

    pass


class RepoNotFoundError(MetadataStoreError):
    """Raised when a repository is not found."""

    pass


class InvalidStatusTransitionError(MetadataStoreError):
    """Raised on invalid status transitions."""

    pass


__all__ = [
    "Neo4jGraphStore",
    "IGraphStore",
    "ArchitectureOverview",
    "VectorSearchResult",
    "VectorIndexNotAvailableError",
    "ChromaVectorStore",
    "SearchResult",
    "MetadataStore",
    "MetadataStoreError",
    "RepoNotFoundError",
    "InvalidStatusTransitionError",
]
