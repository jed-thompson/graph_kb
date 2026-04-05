"""Neo4j-specific storage implementation package.

This package contains the Neo4j-specific implementations of the graph storage
interface, organized into specialized modules:

- connection.py: SessionManager for driver and transaction management
- queries.py: Centralized Cypher query definitions
- node_repository.py: Node CRUD operations
- edge_repository.py: Edge/relationship operations
- vector_repository.py: Vector search operations
- batch_repository.py: Bulk/batch operations
"""

from .batch_repository import BatchRepository
from .connection import ConnectionError, SessionManager, TransactionError
from .edge_repository import EdgeRepository
from .models import UnifiedRAGResult
from .node_repository import NodeRepository
from .queries import (
    BatchQueries,
    EdgeQueries,
    IndexQueries,
    NodeQueries,
    StatsQueries,
    SymbolQueries,
    VectorQueries,
)
from .vector_repository import (
    VectorIndexNotAvailableError,
    VectorRepository,
    VectorSearchResult,
)

__all__ = [
    # Connection management
    "SessionManager",
    "ConnectionError",
    "TransactionError",
    # Repositories
    "NodeRepository",
    "EdgeRepository",
    "VectorRepository",
    "BatchRepository",
    # Vector search types
    "VectorSearchResult",
    "VectorIndexNotAvailableError",
    # RAG result types
    "UnifiedRAGResult",
    # Query classes
    "IndexQueries",
    "NodeQueries",
    "EdgeQueries",
    "VectorQueries",
    "BatchQueries",
    "SymbolQueries",
    "StatsQueries",
]
