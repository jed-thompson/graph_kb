"""Code Visualization Service for graph visualization generation.

This service consolidates VisualizationService functionality, providing
graph visualization generation and rendering. It accesses storage only
through adapters.
"""

import os
from typing import List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..adapters.storage import GraphStatsAdapter
from ..models.visualization import VisGraph, VisualizationResult, VisualizationType
from ..storage import MetadataStore
from ..visualization.querier import GraphQuerier
from ..visualization.renderer import GraphRenderer
from .base_service import BaseGraphKBService

logger = EnhancedLogger(__name__)


class CodeVisualizationService(BaseGraphKBService):
    """Service for interactive graph visualizations and statistics.

    **Purpose**: Generate interactive HTML visualizations of code structure and
    provide graph statistics for understanding repository complexity.

    **Use this service when**:
    - You want to visualize code architecture (modules, files, dependencies)
    - You need to see call graphs or dependency graphs
    - You want to identify hotspots (highly connected symbols)
    - You need to trace specific call chains visually
    - You want graph statistics (node counts, edge counts, complexity metrics)

    **Key capabilities**:
    - Multiple visualization types (architecture, calls, dependencies, hotspots)
    - Interactive HTML rendering with zoom/pan/search
    - Call chain tracing (visualize paths from a specific symbol)
    - Hotspot analysis (find highly connected symbols)
    - Graph statistics (comprehensive metrics about repository structure)

    **Visualization types**:
    - ARCHITECTURE: High-level module and file structure
    - CALLS: Function/method call relationships
    - DEPENDENCIES: File import/dependency graph
    - CALL_CHAIN: Trace calls from a specific symbol
    - HOTSPOTS: Most connected symbols (potential refactoring targets)

    **Example**:
        >>> # Generate architecture visualization
        >>> result = service.generate_visualization(
        ...     repo_id="my-repo",
        ...     viz_type=VisualizationType.ARCHITECTURE,
        ...     folder_path="src/payments"  # Optional scope
        ... )
        >>> print(result.html)  # Interactive HTML visualization
        >>>
        >>> # Save call chain visualization to file
        >>> result = service.generate_visualization_file(
        ...     repo_id="my-repo",
        ...     viz_type=VisualizationType.CALL_CHAIN,
        ...     symbol_name="process_payment",
        ...     direction="outgoing"
        ... )
        >>> print(f"Saved to: {result.html}")
        >>>
        >>> # Get repository statistics
        >>> stats = service.get_graph_stats("my-repo")
        >>> print(f"Total symbols: {stats.total_nodes}")
        >>>
        >>> # Find hotspots (refactoring candidates)
        >>> hotspots = service.get_hotspots("my-repo", top_n=20)

    The service accesses storage only through adapters, following the
    architecture: Services → Adapters → Facade → Repositories
    """

    def __init__(
        self,
        graph_querier: GraphQuerier,
        stats_adapter: GraphStatsAdapter,
        metadata_store: MetadataStore,
        output_dir: str = "/tmp/visualizations",
    ):
        """Initialize the CodeVisualizationService.

        Args:
            graph_querier: Querier for graph visualization data.
            stats_adapter: Adapter for graph statistics.
            metadata_store: Store for repository metadata.
            output_dir: Directory for saving rendered HTML files.
        """
        super().__init__(metadata_store)
        self._querier = graph_querier
        self._stats_adapter = stats_adapter
        self._renderer = GraphRenderer()
        self._output_dir = output_dir

    def generate_visualization(
        self,
        repo_id: str,
        viz_type: VisualizationType,
        folder_path: Optional[str] = None,
        symbol_name: Optional[str] = None,
        direction: str = "outgoing",
        symbol_kinds: Optional[List[str]] = None,
        max_depth: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> VisualizationResult:
        """Generate a visualization for the given parameters.

        Args:
            repo_id: Repository identifier.
            viz_type: Type of visualization to generate.
            folder_path: Optional folder path to scope the visualization.
            symbol_name: Symbol name for call_chain visualization.
            direction: Direction for call_chain ("outgoing" or "incoming").
            symbol_kinds: Filter by symbol kinds (e.g., ['function', 'method']).
            max_depth: Override default traversal depth.
            limit: Override default result limit.

        Returns:
            VisualizationResult with HTML content or error.
        """
        # Validate repository
        validation_error = self.validate_repository(repo_id, strategy="message")
        if validation_error:
            return VisualizationResult(success=False, error=validation_error)

        # Validate folder path if provided
        if folder_path:
            if not self._querier.path_exists(repo_id, folder_path):
                return VisualizationResult(
                    success=False,
                    error=f"Path '{folder_path}' not found in repository '{repo_id}'.",
                )

        try:
            # Query graph based on visualization type
            graph = self._query_graph(
                repo_id,
                viz_type,
                folder_path,
                symbol_name=symbol_name,
                direction=direction,
                symbol_kinds=symbol_kinds,
                max_depth=max_depth,
                limit=limit,
            )

            # Check for empty results
            if not graph.nodes:
                return VisualizationResult(
                    success=True,
                    error=f"No {viz_type.value} data found for the specified scope.",
                    node_count=0,
                    edge_count=0,
                )

            # Generate title
            title = self._build_title(repo_id, viz_type, folder_path)

            # Render to HTML
            html = self._renderer.render(graph, title)

            return VisualizationResult(
                success=True,
                html=html,
                node_count=len(graph.nodes),
                edge_count=len(graph.edges),
            )

        except Exception as e:
            logger.error(
                f"Failed to generate visualization for repo {repo_id}: {e}",
                exc_info=True,
            )
            return VisualizationResult(
                success=False,
                error=f"Failed to generate visualization: {str(e)}",
            )

    def generate_visualization_file(
        self,
        repo_id: str,
        viz_type: VisualizationType,
        folder_path: Optional[str] = None,
        symbol_name: Optional[str] = None,
        direction: str = "outgoing",
        symbol_kinds: Optional[List[str]] = None,
        max_depth: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> VisualizationResult:
        """Generate a visualization and save to file.

        Args:
            repo_id: Repository identifier.
            viz_type: Type of visualization to generate.
            folder_path: Optional folder path to scope the visualization.
            symbol_name: Symbol name for call_chain visualization.
            direction: Direction for call_chain ("outgoing" or "incoming").
            symbol_kinds: Filter by symbol kinds.
            max_depth: Override default traversal depth.
            limit: Override default result limit.

        Returns:
            VisualizationResult with file path in html field or error.
        """
        # First generate the visualization
        result = self.generate_visualization(
            repo_id,
            viz_type,
            folder_path,
            symbol_name=symbol_name,
            direction=direction,
            symbol_kinds=symbol_kinds,
            max_depth=max_depth,
            limit=limit,
        )

        if not result.success or not result.html:
            return result

        try:
            # Save to file
            os.makedirs(self._output_dir, exist_ok=True)
            filename = f"{repo_id}_{viz_type.value}.html"
            if folder_path:
                safe_path = folder_path.replace("/", "_")
                filename = f"{repo_id}_{safe_path}_{viz_type.value}.html"

            output_path = os.path.join(self._output_dir, filename)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(result.html)

            logger.info(f"Saved visualization to {output_path}")

            # Return result with file path
            return VisualizationResult(
                success=True,
                html=output_path,  # Return path instead of HTML content
                node_count=result.node_count,
                edge_count=result.edge_count,
            )

        except Exception as e:
            logger.error(f"Failed to save visualization file: {e}", exc_info=True)
            return VisualizationResult(
                success=False,
                error=f"Failed to save visualization file: {str(e)}",
            )

    def get_graph_stats(self, repo_id: str):
        """Get comprehensive graph statistics for a repository.

        Args:
            repo_id: The repository ID.

        Returns:
            Graph statistics object.
        """
        return self._stats_adapter.get_stats(repo_id)

    def get_hotspots(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
        top_n: int = 50,
    ) -> VisGraph:
        """Get the most connected symbols (hotspots) in the repository.

        Args:
            repo_id: The repository ID.
            folder_path: Optional folder path to scope the analysis.
            top_n: Number of hotspots to return.

        Returns:
            VisGraph containing hotspot nodes and their connections.
        """
        return self._querier.query_hotspots(
            repo_id=repo_id,
            folder_path=folder_path,
            top_n=top_n,
            min_connections=5,
        )

    def _query_graph(
        self,
        repo_id: str,
        viz_type: VisualizationType,
        folder_path: Optional[str] = None,
        symbol_name: Optional[str] = None,
        direction: str = "outgoing",
        symbol_kinds: Optional[List[str]] = None,
        max_depth: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> VisGraph:
        """Query the graph based on visualization type.

        Args:
            repo_id: Repository identifier.
            viz_type: Type of visualization.
            folder_path: Optional folder path filter.
            symbol_name: Symbol name for call_chain.
            direction: Direction for call_chain.
            symbol_kinds: Filter by symbol kinds.
            max_depth: Override default traversal depth.
            limit: Override default result limit.

        Returns:
            VisGraph with queried nodes and edges.
        """
        if viz_type == VisualizationType.ARCHITECTURE:
            return self._querier.query_architecture(
                repo_id, folder_path, limit=limit or 500
            )
        elif viz_type == VisualizationType.CALLS:
            return self._querier.query_calls(
                repo_id,
                folder_path,
                limit=limit or 5000,
                max_depth=max_depth,
                symbol_kinds=symbol_kinds,
            )
        elif viz_type == VisualizationType.DEPENDENCIES:
            return self._querier.query_dependencies(
                repo_id, folder_path, limit=limit or 2000, max_depth=max_depth
            )
        elif viz_type == VisualizationType.FULL:
            return self._querier.query_full(repo_id, folder_path, limit=limit or 500)
        elif viz_type == VisualizationType.COMPREHENSIVE:
            return self._querier.query_comprehensive(
                repo_id, folder_path, limit=limit or 1000
            )
        elif viz_type == VisualizationType.CALL_CHAIN:
            if not symbol_name:
                logger.warning("call_chain visualization requires symbol_name")
                return VisGraph()
            return self._querier.query_call_chain(
                repo_id,
                symbol_name,
                direction,
                max_depth=max_depth or 15,
                limit=limit or 500,
            )
        elif viz_type == VisualizationType.HOTSPOTS:
            return self._querier.query_hotspots(
                repo_id, folder_path, top_n=limit or 50, min_connections=5
            )
        else:
            return VisGraph()

    def _build_title(
        self,
        repo_id: str,
        viz_type: VisualizationType,
        folder_path: Optional[str] = None,
    ) -> str:
        """Build a title for the visualization.

        Args:
            repo_id: Repository identifier.
            viz_type: Type of visualization.
            folder_path: Optional folder path.

        Returns:
            Title string.
        """
        type_names = {
            VisualizationType.ARCHITECTURE: "Architecture",
            VisualizationType.CALLS: "Call Graph",
            VisualizationType.DEPENDENCIES: "Dependencies",
            VisualizationType.FULL: "Full Graph",
            VisualizationType.COMPREHENSIVE: "Comprehensive Graph",
            VisualizationType.CALL_CHAIN: "Call Chain",
            VisualizationType.HOTSPOTS: "Hotspots",
        }

        type_name = type_names.get(viz_type, viz_type.value.title())

        if folder_path:
            return f"{type_name}: {repo_id}/{folder_path}"
        return f"{type_name}: {repo_id}"
