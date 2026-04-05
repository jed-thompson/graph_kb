"""Adapter layer for Graph KB system.

This module consolidates all adapter patterns used throughout the system,
providing clean abstractions for storage access and external service integration.

The adapter layer follows the Adapter Pattern to:
1. Abstract storage layer complexity from services
2. Provide consistent interfaces for external services
3. Enable easy swapping of implementations
4. Isolate external dependencies

Structure:
- storage/: Adapters for storage layer (Neo4j, ChromaDB, etc.)
- external/: Adapters for external services (LLM, embedders, etc.)
- models.py: Data models for adapter configuration and health
"""

# Import external adapters
from .external import (
    EmbedderAdapter,
    LLMAdapter,
)
from .models import (
    AdapterConfig,
    AdapterHealth,
    AdapterRegistry,
    AdapterStatus,
    AdapterType,
    ExternalAdapterMetrics,
    StorageAdapterMetrics,
)

# Import storage adapters
from .storage import (
    GraphRetrieverAdapter,
    HybridCypherRetrieverAdapter,
    HybridGraphTraversalRetriever,
    Neo4jVectorCypherRetrieverAdapter,
    VectorCypherRetrieverAdapter,
)

__all__ = [
    # Models
    "AdapterType",
    "AdapterStatus",
    "AdapterConfig",
    "AdapterHealth",
    "StorageAdapterMetrics",
    "ExternalAdapterMetrics",
    "AdapterRegistry",

    # Storage adapters
    "GraphRetrieverAdapter",
    "VectorCypherRetrieverAdapter",
    "Neo4jVectorCypherRetrieverAdapter",
    "HybridCypherRetrieverAdapter",
    "HybridGraphTraversalRetriever",

    # External adapters
    "LLMAdapter",
    "EmbedderAdapter",
]
