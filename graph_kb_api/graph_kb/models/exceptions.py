"""Custom exceptions for the graph_kb package.

This module contains all custom exception classes used throughout the graph_kb
package, organized by their functional area.
"""


# ============================================================================
# Indexing Exceptions
# ============================================================================

class IndexerServiceV2Error(Exception):
    """Base exception for IndexerServiceV2 errors."""
    pass


class EmbeddingDimensionError(Exception):
    """Raised when embedding dimensions don't match expected value."""
    pass


# ============================================================================
# Storage Exceptions
# ============================================================================

class MetadataStoreError(Exception):
    """Base exception for metadata store errors."""
    pass


class RepoNotFoundError(MetadataStoreError):
    """Raised when a repository is not found in the metadata store."""
    pass


class InvalidStatusTransitionError(MetadataStoreError):
    """Raised when an invalid status transition is attempted."""
    pass


# ============================================================================
# Analysis Exceptions
# ============================================================================

class AnalysisV2Error(Exception):
    """Base exception for Analysis V2 errors."""
    pass


class RepositoryNotFoundError(AnalysisV2Error):
    """Raised when a repository is not found during analysis."""
    pass


class RepositoryNotReadyError(AnalysisV2Error):
    """Raised when a repository is not ready for querying."""

    def __init__(self, repo_id: str, status):
        """Initialize with repo_id and status.

        Args:
            repo_id: Repository identifier
            status: Current RepoStatus enum value
        """
        self.repo_id = repo_id
        self.status = status
        super().__init__(
            f"Repository '{repo_id}' is not ready for querying. "
            f"Current status: {status.value}"
        )


class SymbolNotFoundError(AnalysisV2Error):
    """Raised when a symbol is not found in the graph."""
    pass


class RetrieverConfigurationError(AnalysisV2Error):
    """Raised when retriever configuration is invalid.

    This exception is raised when:
    - Neo4j connection cannot be established
    - Vector index is not found
    - Invalid retriever parameters are provided
    """
    pass


class EmbedderNotConfiguredError(AnalysisV2Error):
    """Raised when embedder is required but not configured.

    This exception is raised when:
    - Vector search is requested but no embedder is available
    - Embedding generation fails due to missing configuration
    """
    pass


class LLMNotConfiguredError(AnalysisV2Error):
    """Raised when LLM is required but not configured.

    This exception is raised when:
    - Narrative generation is requested but no LLM is available
    - LLM-dependent operations are called without LLM configuration
    """
    pass


class TraversalError(Exception):
    """Raised when graph traversal encounters an error."""
    pass


class ValidationError(Exception):
    """Raised when validation fails."""
    pass
