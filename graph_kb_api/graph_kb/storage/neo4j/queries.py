"""Centralized Cypher query definitions for Neo4j graph operations.

This module is DEPRECATED. Please use `src.graph_kb.storage.queries.*` instead.
It re-exports classes for backward compatibility.
"""

from ..queries.batch_queries import BatchQueries
from ..queries.edge_queries import EdgeQueries
from ..queries.index_queries import IndexQueries
from ..queries.node_queries import NodeQueries
from ..queries.stats_queries import StatsQueries
from ..queries.symbol_queries import SymbolQueries
from ..queries.vector_queries import TraversalQueries, VectorQueries

# Re-export for compatibility
__all__ = [
    "NodeQueries",
    "EdgeQueries",
    "VectorQueries",
    "TraversalQueries",
    "BatchQueries",
    "IndexQueries",
    "SymbolQueries",
    "StatsQueries",
]
