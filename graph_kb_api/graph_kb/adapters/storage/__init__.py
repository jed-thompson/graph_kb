"""Storage adapters for Graph KB system.

This module contains adapters that abstract storage layer access,
providing clean interfaces for graph retrieval, vector search, and
Neo4j GraphRAG operations.
"""

from .graph_retriever import GraphRetrieverAdapter
from .interfaces import IDirectoryAdapter, ISymbolQueryAdapter, ITraversalAdapter
from .neo4j_graphrag_retriever import (
    HybridCypherRetrieverAdapter,
    HybridGraphTraversalRetriever,
)
from .neo4j_graphrag_retriever import (
    VectorCypherRetrieverAdapter as Neo4jVectorCypherRetrieverAdapter,
)
from .stats_adapter import GraphStatsAdapter
from .symbol_query_adapter import SymbolQueryAdapter
from .traversal_adapter import TraversalAdapter
from .vector_retriever import VectorCypherRetrieverAdapter

__all__ = [
    "GraphRetrieverAdapter",
    "VectorCypherRetrieverAdapter",
    "Neo4jVectorCypherRetrieverAdapter",
    "HybridCypherRetrieverAdapter",
    "HybridGraphTraversalRetriever",
    "SymbolQueryAdapter",
    "TraversalAdapter",
    "GraphStatsAdapter",
    "ITraversalAdapter",
    "ISymbolQueryAdapter",
    "IDirectoryAdapter",
]
