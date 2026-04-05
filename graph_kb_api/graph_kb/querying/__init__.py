"""Graph querying module.

This module handles graph queries and traversal operations for exploring
relationships and patterns in the knowledge graph.

It provides:
- TraversalResult and related models for graph traversal
- PathExtractor for extracting structured paths from traversal results
- EdgeGrouper for organizing edges by type and direction
"""

from .models import (
    ArchitectureQuery,
    ArchitectureResult,
    ContextPacket,
    GraphRAGResult,
    MermaidDiagram,
    NeighborhoodResult,
    PathResult,
    PatternMatchResult,
    QueryConfig,
    QueryResult,
    QueryType,
    SymbolMatch,
    TraversalDirection,
    TraversalEdge,
    TraversalResult,
)
from .traversal_utils import EdgeGrouper, PathExtractor

__all__ = [
    # Models
    "TraversalResult",
    "TraversalEdge",
    "ContextPacket",
    "MermaidDiagram",
    "GraphRAGResult",
    "QueryType",
    "TraversalDirection",
    "QueryConfig",
    "QueryResult",
    "PathResult",
    "NeighborhoodResult",
    "SymbolMatch",
    "PatternMatchResult",
    "ArchitectureQuery",
    "ArchitectureResult",
    # Utilities
    "PathExtractor",
    "EdgeGrouper",
]
