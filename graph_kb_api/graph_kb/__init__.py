"""
Graph Knowledge Base module for code-aware repository ingestion.

This module provides functionality for:
- Ingesting GitHub repositories
- Building a graph knowledge base of code structure
- Semantic search over code embeddings
- Graph traversal for code flow analysis
"""

# Lazy imports to avoid circular dependency:
#   database.repositories → graph_kb.models.enums → graph_kb.__init__
#   → graph_kb.facade → graph_kb.storage → database.metadata_service
#   → database.repositories  (circular!)


def __getattr__(name: str):
    if name in ("GraphKBFacade", "get_facade"):
        from .facade import GraphKBFacade, get_facade

        globals()["GraphKBFacade"] = GraphKBFacade
        globals()["get_facade"] = get_facade
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__version__ = "0.1.0"

__all__ = [
    "GraphKBFacade",
    "get_facade",
]
