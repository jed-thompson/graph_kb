"""Analysis module for code understanding using neo4j-graphrag.

This module provides comprehensive code analysis functionality including:
- Entry point discovery
- Data flow tracing
- Domain concept extraction
- Graph-based retrieval (GraphRAG)
- Narrative summary generation
- Use case analysis

Key components:
- AnalysisServiceV2: Main orchestration service
- GraphQueryService: Graph query patterns and validation
- GraphRAGService: Graph RAG retrieval pipeline
- RecursiveGraphTraverser: Multi-hop graph traversal
"""

# Configuration
from ..adapters.external import (
    EmbedderAdapter,
    LLMAdapter,
)

# Adapters
from ..adapters.storage import (
    GraphRetrieverAdapter,
    VectorCypherRetrieverAdapter,
)

# Import exceptions from the correct location
# Exceptions
from ..models import (
    AnalysisV2Error,
    EmbedderNotConfiguredError,
    LLMNotConfiguredError,
    RepositoryNotFoundError,
    RepositoryNotReadyError,
    RetrieverConfigurationError,
    SymbolNotFoundError,
)

# Models (shared)
from ..models.analysis import (
    CodeAnalysisResult,
    DataFlow,
    DataFlowStep,
    DomainConcept,
    DomainRelationship,
    EntryPoint,
    NarrativeSummary,
)

# Enums (shared)
from ..models.analysis_enums import (
    DomainCategory,
    EntryPointType,
    RelationType,
    StepType,
)
from ..models.config import AnalysisConfig, RetrieverConfig
from ..models.retrieval import SymbolMatch

# Traversal models
from ..querying.models import (
    ContextPacket,
    GraphRAGResult,
    MermaidDiagram,
    TraversalEdge,
    TraversalResult,
)

# Analyzers
from .analyzers import (
    DataFlowTracerV2,
    DomainExtractorV2,
    EntryPointAnalyzerV2,
)

# Builders
from .builders import (
    ContextPacketBuilderV2,
    NarrativeGeneratorV2,
    SubgraphVisualizerV2,
)

# Main services
from .service import AnalysisServiceV2

# Aliases for backward compatibility (V2 as primary)
AnalysisService = AnalysisServiceV2
EntryPointAnalyzer = EntryPointAnalyzerV2
DataFlowTracer = DataFlowTracerV2
DomainExtractor = DomainExtractorV2
ContextPacketBuilder = ContextPacketBuilderV2
NarrativeGenerator = NarrativeGeneratorV2
SubgraphVisualizer = SubgraphVisualizerV2

__all__ = [
    # Configuration
    "AnalysisConfig",
    "RetrieverConfig",
    # Enums
    "EntryPointType",
    "DomainCategory",
    "RelationType",
    "StepType",
    # Models
    "EntryPoint",
    "DataFlowStep",
    "DataFlow",
    "DomainConcept",
    "DomainRelationship",
    "NarrativeSummary",
    "CodeAnalysisResult",
    # Traversal models
    "TraversalEdge",
    "TraversalResult",
    "ContextPacket",
    "MermaidDiagram",
    "GraphRAGResult",
    # Services
    "AnalysisService",
    "AnalysisServiceV2",
    # Analyzers
    "EntryPointAnalyzer",
    "EntryPointAnalyzerV2",
    "DataFlowTracer",
    "DataFlowTracerV2",
    "DomainExtractor",
    "DomainExtractorV2",
    # Builders
    "ContextPacketBuilder",
    "ContextPacketBuilderV2",
    "NarrativeGenerator",
    "NarrativeGeneratorV2",
    "SubgraphVisualizer",
    "SubgraphVisualizerV2",
    # Adapters
    "GraphRetrieverAdapter",
    "VectorCypherRetrieverAdapter",
    "LLMAdapter",
    "EmbedderAdapter",
    # Exceptions
    "RepositoryNotFoundError",
    "RepositoryNotReadyError",
    "SymbolNotFoundError",
    "SymbolMatch",
    "AnalysisV2Error",
    "RetrieverConfigurationError",
    "EmbedderNotConfiguredError",
    "LLMNotConfiguredError",
]
