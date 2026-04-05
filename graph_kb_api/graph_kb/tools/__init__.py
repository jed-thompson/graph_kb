"""Chat agent tools for code search and navigation.

This module provides a registry of tools that can be used by the chat agent
for code-aware operations on indexed repositories.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..adapters.storage import GraphRetrieverAdapter
from ..storage import MetadataStore
from ..storage.graph_store import Neo4jGraphStore
from .analyze_hotspots import AnalyzeHotspotsResult, AnalyzeHotspotsTool
from .find_entry_points import FindEntryPointsResult, FindEntryPointsTool
from .get_architecture_overview import ArchitectureResult, GetArchitectureOverviewTool
from .get_file_snippet import GetFileSnippetTool, SnippetResult
from .get_flow_between_symbols import FlowResult, GetFlowBetweenSymbolsTool
from .get_graph_stats import GetGraphStatsTool, GraphStatsResult
from .get_symbol_details import GetSymbolDetailsResult, GetSymbolDetailsTool
from .get_symbol_references import GetSymbolReferencesTool, SymbolReferencesResult
from .list_files import ListFilesResult, ListFilesTool
from .search_repo import SearchRepoTool, SearchResult
from .trace_data_flow import TraceDataFlowResult, TraceDataFlowTool
from .visualize_graph import VisualizeGraphResult, VisualizeGraphTool

if TYPE_CHECKING:
    from ..services.analysis_service import CodeAnalysisService
    from ..services.code_visualization_service import CodeVisualizationService
    from ..services.query_service import CodeQueryService
    from ..services.retrieval_service import CodeRetrievalService

logger = EnhancedLogger(__name__)

# Export tool classes
__all__ = [
    "SearchRepoTool",
    "SearchResult",
    "GetFileSnippetTool",
    "SnippetResult",
    "GetFlowBetweenSymbolsTool",
    "FlowResult",
    "GetArchitectureOverviewTool",
    "ArchitectureResult",
    "ListFilesTool",
    "ListFilesResult",
    "FindEntryPointsTool",
    "FindEntryPointsResult",
    "GetSymbolReferencesTool",
    "SymbolReferencesResult",
    "TraceDataFlowTool",
    "TraceDataFlowResult",
    "VisualizeGraphTool",
    "VisualizeGraphResult",
    "GetGraphStatsTool",
    "GraphStatsResult",
    "AnalyzeHotspotsTool",
    "AnalyzeHotspotsResult",
    "GetSymbolDetailsTool",
    "GetSymbolDetailsResult",
    "ToolRegistry",
    "create_tool_registry",
]


@dataclass
class ToolDefinition:
    """Definition of a tool for LLM function calling."""

    name: str
    description: str
    schema: Dict[str, Any]
    handler: Callable[..., Any]


class ToolRegistry:
    """Registry for chat agent tools.

    This class manages the registration and invocation of tools
    that can be used by the chat agent for code-aware operations.
    """

    def __init__(self):
        """Initialize the tool registry."""
        self._tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool with the registry.

        Args:
            name: The unique name of the tool.
            description: A description of what the tool does.
            schema: The JSON schema for the tool's parameters.
            handler: The function to call when the tool is invoked.
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            schema=schema,
            handler=handler,
        )
        logger.debug(f"Registered tool: {name}")

    def unregister(self, name: str) -> bool:
        """Unregister a tool from the registry.

        Args:
            name: The name of the tool to unregister.

        Returns:
            True if the tool was unregistered, False if not found.
        """
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"Unregistered tool: {name}")
            return True
        return False

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name.

        Args:
            name: The name of the tool.

        Returns:
            The ToolDefinition if found, None otherwise.
        """
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tool names.

        Returns:
            List of tool names.
        """
        return list(self._tools.keys())

    def get_schemas_for_llm(self) -> List[Dict[str, Any]]:
        """Get tool schemas formatted for LLM function calling.

        Returns:
            List of tool schemas in OpenAI function calling format.
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.schema,
                    },
                }
            )
        return schemas

    def invoke(
        self,
        name: str,
        **kwargs: Any,
    ) -> Union[
        SearchResult, SnippetResult, FlowResult, ArchitectureResult, Dict[str, Any]
    ]:
        """Invoke a tool by name.

        Args:
            name: The name of the tool to invoke.
            **kwargs: The arguments to pass to the tool.

        Returns:
            The result from the tool invocation.

        Raises:
            ValueError: If the tool is not found.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Tool '{name}' not found in registry")

        logger.debug(f"Invoking tool: {name} with args: {kwargs}")
        return tool.handler(**kwargs)

    def invoke_from_llm_call(
        self,
        function_name: str,
        arguments: Dict[str, Any],
    ) -> Union[
        SearchResult, SnippetResult, FlowResult, ArchitectureResult, Dict[str, Any]
    ]:
        """Invoke a tool from an LLM function call.

        Args:
            function_name: The name of the function to call.
            arguments: The arguments from the LLM.

        Returns:
            The result from the tool invocation.

        Raises:
            ValueError: If the tool is not found.
        """
        return self.invoke(function_name, **arguments)


def create_tool_registry(
    query_service: Optional["CodeQueryService"] = None,
    retrieval_service: Optional["CodeRetrievalService"] = None,
    visualization_service: Optional["CodeVisualizationService"] = None,
    analysis_service: Optional["CodeAnalysisService"] = None,
    retriever_adapter: Optional[GraphRetrieverAdapter] = None,
    # Legacy parameters (deprecated - will be removed)
    retriever: Optional[Any] = None,
    graph_store: Optional[Neo4jGraphStore] = None,
    metadata_store: Optional[MetadataStore] = None,
) -> ToolRegistry:
    """Create and configure a tool registry with all available tools.

    This function uses the new consolidated service architecture:
    - query_service: CodeQueryService for symbol queries
    - retrieval_service: CodeRetrievalService for semantic search
    - visualization_service: CodeVisualizationService for visualizations
    - analysis_service: CodeAnalysisService for entry points and data flow analysis
    - retriever_adapter: GraphRetrieverAdapter for advanced analysis tools (deprecated)

    Args:
        query_service: CodeQueryService for symbol queries (required).
        retrieval_service: CodeRetrievalService for semantic search (optional).
        visualization_service: CodeVisualizationService for visualizations (optional).
        analysis_service: CodeAnalysisService for entry points and data flow (optional).
        retriever_adapter: Optional GraphRetrieverAdapter (deprecated, use analysis_service).
        retriever: DEPRECATED - Use retrieval_service instead.
        graph_store: DEPRECATED - Services are provided via container.
        metadata_store: DEPRECATED - Services are provided via container.

    Returns:
        A configured ToolRegistry instance.
    """
    import warnings

    # Warn about deprecated parameters
    if retriever is not None:
        warnings.warn(
            "retriever parameter is deprecated. Use retrieval_service instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    if graph_store is not None or metadata_store is not None:
        warnings.warn(
            "graph_store and metadata_store parameters are deprecated. "
            "Services should be provided via the service container.",
            DeprecationWarning,
            stacklevel=2,
        )

    registry = ToolRegistry()

    # Use provided query_service (required)
    query_service_internal = query_service
    if query_service_internal is None:
        raise ValueError("query_service is required")

    # Use provided retrieval_service (optional but recommended)
    if retrieval_service is None and retriever is not None:
        warnings.warn(
            "retriever parameter is deprecated and will be removed. Pass retrieval_service instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise ValueError(
            "retriever parameter is deprecated. Please pass retrieval_service instead. "
            "Migration: from graph_kb_api.graph_kb import get_facade; "
            "facade = get_facade(); retrieval_service=facade.retrieval_service"
        )

    # Register search_repo tool if retrieval_service is available
    if retrieval_service is not None:
        search_tool = SearchRepoTool(
            retrieval_service=retrieval_service,
        )
        registry.register(
            name=SearchRepoTool.SCHEMA["name"],
            description=SearchRepoTool.SCHEMA["description"],
            schema=SearchRepoTool.SCHEMA["parameters"],
            handler=search_tool.invoke,
        )

    # Register tools that require query_service
    if query_service_internal is not None:
        # Register get_file_snippet tool
        snippet_tool = GetFileSnippetTool(query_service=query_service_internal)
        registry.register(
            name=GetFileSnippetTool.SCHEMA["name"],
            description=GetFileSnippetTool.SCHEMA["description"],
            schema=GetFileSnippetTool.SCHEMA["parameters"],
            handler=snippet_tool.invoke,
        )

        flow_tool = GetFlowBetweenSymbolsTool(query_service=query_service_internal)
        registry.register(
            name=GetFlowBetweenSymbolsTool.SCHEMA["name"],
            description=GetFlowBetweenSymbolsTool.SCHEMA["description"],
            schema=GetFlowBetweenSymbolsTool.SCHEMA["parameters"],
            handler=flow_tool.invoke,
        )

        # Register get_architecture_overview tool (reuse query_service)
        arch_tool = GetArchitectureOverviewTool(query_service=query_service_internal)
        registry.register(
            name=GetArchitectureOverviewTool.SCHEMA["name"],
            description=GetArchitectureOverviewTool.SCHEMA["description"],
            schema=GetArchitectureOverviewTool.SCHEMA["parameters"],
            handler=arch_tool.invoke,
        )

        # Register list_files tool (reuse query_service)
        list_files_tool = ListFilesTool(query_service=query_service_internal)
        registry.register(
            name=ListFilesTool.SCHEMA["name"],
            description=ListFilesTool.SCHEMA["description"],
            schema=ListFilesTool.SCHEMA["parameters"],
            handler=list_files_tool.invoke,
        )

        # Register get_symbol_details tool (new)
        symbol_details_tool = GetSymbolDetailsTool(query_service=query_service_internal)
        registry.register(
            name=GetSymbolDetailsTool.SCHEMA["name"],
            description=GetSymbolDetailsTool.SCHEMA["description"],
            schema=GetSymbolDetailsTool.SCHEMA["parameters"],
            handler=symbol_details_tool.invoke,
        )

    # Register tools that require query_service
    if query_service_internal is not None:
        # Register get_symbol_references tool
        refs_tool = GetSymbolReferencesTool(
            query_service=query_service_internal,
        )
        registry.register(
            name=GetSymbolReferencesTool.SCHEMA["name"],
            description=GetSymbolReferencesTool.SCHEMA["description"],
            schema=GetSymbolReferencesTool.SCHEMA["parameters"],
            handler=refs_tool.invoke,
        )

    # Register tools that require analysis_service
    if analysis_service is not None:
        # Register find_entry_points tool
        entry_points_tool = FindEntryPointsTool(
            analysis_service=analysis_service,
        )
        registry.register(
            name=FindEntryPointsTool.SCHEMA["name"],
            description=FindEntryPointsTool.SCHEMA["description"],
            schema=FindEntryPointsTool.SCHEMA["parameters"],
            handler=entry_points_tool.invoke,
        )

        # Register trace_data_flow tool
        trace_tool = TraceDataFlowTool(
            analysis_service=analysis_service,
        )
        registry.register(
            name=TraceDataFlowTool.SCHEMA["name"],
            description=TraceDataFlowTool.SCHEMA["description"],
            schema=TraceDataFlowTool.SCHEMA["parameters"],
            handler=trace_tool.invoke,
        )

    # Register visualization tools (new)
    if visualization_service is not None:
        # Register visualize_graph tool
        visualize_tool = VisualizeGraphTool(visualization_service=visualization_service)
        registry.register(
            name=VisualizeGraphTool.SCHEMA["name"],
            description=VisualizeGraphTool.SCHEMA["description"],
            schema=VisualizeGraphTool.SCHEMA["parameters"],
            handler=visualize_tool.invoke,
        )

        # Register get_graph_stats tool
        stats_tool = GetGraphStatsTool(visualization_service=visualization_service)
        registry.register(
            name=GetGraphStatsTool.SCHEMA["name"],
            description=GetGraphStatsTool.SCHEMA["description"],
            schema=GetGraphStatsTool.SCHEMA["parameters"],
            handler=stats_tool.invoke,
        )

        # Register analyze_hotspots tool
        hotspots_tool = AnalyzeHotspotsTool(visualization_service=visualization_service)
        registry.register(
            name=AnalyzeHotspotsTool.SCHEMA["name"],
            description=AnalyzeHotspotsTool.SCHEMA["description"],
            schema=AnalyzeHotspotsTool.SCHEMA["parameters"],
            handler=hotspots_tool.invoke,
        )

    logger.info(f"Created tool registry with {len(registry.list_tools())} tools")
    return registry
