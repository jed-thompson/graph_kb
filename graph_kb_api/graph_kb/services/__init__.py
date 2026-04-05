"""Consolidated services for Graph KB.

This module provides the consolidated service layer that sits between
tools/commands and the storage/adapter layer. Services encapsulate
business logic and orchestrate operations across multiple adapters.

Services:
- BaseGraphKBService: Base class with common functionality (validation, config, metadata)
- CodeQueryService: Symbol resolution, path finding, neighbor queries
- CodeRetrievalService: Hybrid vector + graph search, context building
- CodeAnalysisService: Entry points, data flow, domain extraction, narrative
- CodeVisualizationService: Graph visualization generation
- IngestionService: Repository ingestion pipeline orchestration

Note: For facade access, import from graph_kb_api.graph_kb:
    from graph_kb_api.graph_kb import GraphKBFacade, get_facade
"""

from .analysis_service import CodeAnalysisService
from .base_service import BaseGraphKBService
from .code_visualization_service import CodeVisualizationService
from .ingestion_service import IngestionService
from .query_service import CodeQueryService
from .retrieval_service import CodeRetrievalService

__all__ = [
    "BaseGraphKBService",
    "CodeQueryService",
    "CodeRetrievalService",
    "CodeAnalysisService",
    "CodeVisualizationService",
    "IngestionService",
]
