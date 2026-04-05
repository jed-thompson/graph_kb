"""Interface definitions for graph storage operations.

This package defines abstract interfaces (protocols) for graph storage,
enabling dependency injection, testing with mocks, and potential
backend swapping.
"""

from .graph_store import (
    ArchitectureOverview,
    IGraphStore,
    VectorSearchResult,
)
from .repositories import (
    IBatchRepository,
    IEdgeRepository,
    INodeRepository,
    IVectorRepository,
)

__all__ = [
    "IGraphStore",
    "VectorSearchResult",
    "ArchitectureOverview",
    "INodeRepository",
    "IEdgeRepository",
    "IVectorRepository",
    "IBatchRepository",
]
