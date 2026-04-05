"""Code Query Service for symbol resolution and graph navigation.

This service consolidates GraphQueryService functionality, providing
symbol resolution, path finding, and neighbor queries. It accesses
storage only through adapters, not directly through the facade.
"""

from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..adapters.storage import GraphStatsAdapter, SymbolQueryAdapter, TraversalAdapter
from ..models.base import GraphNode
from ..models.enums import GraphEdgeType
from ..models.retrieval import SymbolMatch
from ..querying.models import TraversalResult
from ..storage import MetadataStore
from ..storage.graph_store import ArchitectureOverview
from .base_service import BaseGraphKBService

logger = EnhancedLogger(__name__)


class CodeQueryService(BaseGraphKBService):
    """Service for precise graph queries and symbol lookups.

    **Purpose**: Direct, deterministic graph navigation when you know what you're
    looking for (symbol names, IDs, or patterns).

    **Use this service when**:
    - You have exact symbol names or IDs to look up
    - You need to explore graph structure (what calls what, what imports what)
    - You want deterministic, repeatable results
    - You're building tools that need precise lookups

    **Key capabilities**:
    - Symbol resolution (name → ID)
    - Path finding between symbols
    - Neighbor queries (callers/callees)
    - Recursive graph traversal
    - Repository validation

    **Contrast with CodeRetrievalService**:
    - CodeQueryService: Exact lookups, graph traversal, no ranking
    - CodeRetrievalService: Semantic search, natural language queries, ranked results

    **Example**:
        >>> # Find a specific symbol by name
        >>> symbol_id = service.resolve_symbol_id("my-repo", "UserController")
        >>>
        >>> # Get all functions it calls
        >>> callees = service.get_neighbors(symbol_id, ["CALLS"], "outgoing")
        >>>
        >>> # Find path between two symbols
        >>> path = service.find_call_path(from_id, to_id, max_hops=5)

    The service accesses storage only through adapters, following the
    architecture: Services → Adapters → Facade → Repositories
    """

    def __init__(
        self,
        symbol_adapter: SymbolQueryAdapter,
        traversal_adapter: TraversalAdapter,
        metadata_store: MetadataStore,
        stats_adapter: Optional[GraphStatsAdapter] = None,
    ):
        """Initialize the CodeQueryService.

        Args:
            symbol_adapter: Adapter for symbol query operations.
            traversal_adapter: Adapter for graph traversal operations.
            metadata_store: Store for repository metadata.
            stats_adapter: Optional adapter for graph statistics (includes architecture).
        """
        super().__init__(metadata_store)
        self._symbol_adapter = symbol_adapter
        self._traversal_adapter = traversal_adapter
        self._stats_adapter = stats_adapter

    def resolve_symbol_id(self, repo_id: str, symbol: str) -> Optional[str]:
        """Resolve a symbol name to its ID in the graph.

        If the symbol is already an ID (exists in graph), return it.
        Otherwise, search for a symbol with that name.

        Args:
            repo_id: The repository ID.
            symbol: The symbol name or ID.

        Returns:
            The symbol ID if found, None otherwise.
        """
        # Search for symbols by name using adapter
        symbol_ids = self._symbol_adapter.search_symbols_by_name(repo_id, symbol)

        if symbol_ids:
            return symbol_ids[0]  # Return first match

        return None

    def get_symbols_by_pattern(
        self,
        repo_id: str,
        name_pattern: Optional[str] = None,
        file_pattern: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 100,
    ) -> List[SymbolMatch]:
        """Get symbols matching specified patterns.

        Args:
            repo_id: The repository ID.
            name_pattern: Regex pattern for symbol name.
            file_pattern: Regex pattern for file path.
            kind: Symbol kind filter (function, class, method).
            limit: Maximum number of results.

        Returns:
            List of matching SymbolMatch objects.
        """
        # Use adapter for symbol queries
        results = self._symbol_adapter.get_symbols_by_pattern(
            repo_id=repo_id,
            name_pattern=name_pattern,
            file_pattern=file_pattern,
            kind=kind,
            limit=limit,
        )

        # Convert adapter results to SymbolMatch objects
        return [
            SymbolMatch(
                id=result["id"],
                name=result["name"],
                kind=result["kind"],
                file_path=result["file_path"],
                docstring=result.get("docstring"),
            )
            for result in results
        ]

    def find_call_path(
        self,
        from_id: str,
        to_id: str,
        max_hops: int = 5,
        edge_types: Optional[List[str]] = None,
    ) -> Optional[List[str]]:
        """Find the call/import path between two symbols.

        Args:
            from_id: ID of the source symbol.
            to_id: ID of the target symbol.
            max_hops: Maximum number of hops in the path.
            edge_types: List of edge types to traverse. If None, uses semantic edges fallback.

        Returns:
            List of node IDs in the path, or None if no path exists.

        Note:
            For repository-aware edge detection, callers should get available edges
            through GraphRetrieverAdapter.get_available_edge_types() and pass them
            as edge_types parameter.
        """
        # Note: This requires EdgeRepository.find_path which is already
        # available through the facade. For now, we'll need to access
        # the graph_store through the adapter's internal reference.
        # TODO: Consider adding find_path to TraversalAdapter

        if edge_types is None:
            # Use semantic edges as fallback when no specific edges provided
            edge_types = GraphEdgeType.semantic_edges()

        # Temporary workaround: access through adapter's graph_store
        return self._traversal_adapter._graph_store.find_path(
            from_id=from_id,
            to_id=to_id,
            edge_types=edge_types,
            max_hops=max_hops,
        )

    def get_neighbors(
        self,
        node_id: str,
        edge_types: Optional[List[str]] = None,
        direction: str = "outgoing",
        limit: int = 100,
    ) -> List[GraphNode]:
        """Get neighboring nodes connected by specified edge types.

        Args:
            node_id: The ID of the source node.
            edge_types: List of edge type names to traverse. If None, uses CALLS as fallback.
            direction: "outgoing", "incoming", or "both".
            limit: Maximum number of neighbors to return.

        Returns:
            List of neighboring GraphNode objects.

        Note:
            For repository-aware edge detection, callers should get available edges
            through GraphRetrieverAdapter.get_available_edge_types() and pass them
            as edge_types parameter.
        """
        if edge_types is None:
            # Use CALLS as fallback when no specific edges provided
            edge_types = [GraphEdgeType.CALLS.value]

        # Access through adapter's graph_store (temporary)
        # TODO: Consider adding get_neighbors to TraversalAdapter
        return self._traversal_adapter._graph_store.get_neighbors(
            node_id=node_id,
            edge_types=edge_types,
            direction=direction,
            limit=limit,
        )

    def get_reachable_subgraph(
        self,
        start_id: str,
        max_depth: int = 5,
        allowed_edges: Optional[List[str]] = None,
        direction: str = "outgoing",
        repo_id: Optional[str] = None,
    ) -> TraversalResult:
        """Get all nodes reachable from start within max_depth hops.

        Uses the TraversalAdapter for multi-hop graph expansion.

        Args:
            start_id: The ID of the starting node.
            max_depth: Maximum traversal depth (default 5, max 10).
            allowed_edges: List of edge types to traverse. If None, uses semantic edges fallback.
            direction: "outgoing", "incoming", or "both".
            repo_id: Repository ID for repository-aware edge detection (unused in current implementation).

        Returns:
            TraversalResult containing all discovered nodes and edges.

        Note:
            For repository-aware edge detection, callers should get available edges
            through GraphRetrieverAdapter.get_available_edge_types() and pass them
            as allowed_edges parameter.
        """
        if allowed_edges is None:
            # Use semantic edges as fallback when no specific edges provided
            allowed_edges = GraphEdgeType.semantic_edges()

        return self._traversal_adapter.get_reachable_subgraph(
            start_id=start_id,
            max_depth=max_depth,
            allowed_edges=allowed_edges,
            direction=direction,
        )

    def get_bidirectional_neighborhood(
        self,
        node_id: str,
        max_depth: int = 3,
        allowed_edges: Optional[List[str]] = None,
        repo_id: Optional[str] = None,
    ) -> TraversalResult:
        """Get both callers (incoming) and callees (outgoing) of a symbol.

        Args:
            node_id: The ID of the central node.
            max_depth: Maximum traversal depth in each direction.
            allowed_edges: List of edge types to traverse. If None, uses semantic edges fallback.
            repo_id: Repository ID for repository-aware edge detection (unused in current implementation).

        Returns:
            TraversalResult containing nodes and edges from both directions.

        Note:
            For repository-aware edge detection, callers should get available edges
            through GraphRetrieverAdapter.get_available_edge_types() and pass them
            as allowed_edges parameter.
        """
        if allowed_edges is None:
            # Use semantic edges as fallback when no specific edges provided
            allowed_edges = GraphEdgeType.semantic_edges()

        return self._traversal_adapter.get_bidirectional_neighborhood(
            node_id=node_id,
            max_depth=max_depth,
            allowed_edges=allowed_edges,
        )

    def build_path_details(self, path_ids: List[str]) -> List[Dict[str, Any]]:
        """Build detailed information for each node in a path.

        Args:
            path_ids: List of node IDs in the path.

        Returns:
            List of dictionaries with node details.
        """
        details = []

        for node_id in path_ids:
            try:
                # Access through adapter's graph_store (temporary)
                node = self._traversal_adapter._graph_store.get_node(node_id)
                if node:
                    details.append(
                        {
                            "id": node.id,
                            "type": node.type.value,
                            "name": node.attrs.get("name", node_id.split(":")[-1]),
                            "file_path": node.attrs.get("file_path"),
                            "summary": node.summary,
                        }
                    )
                else:
                    details.append(
                        {
                            "id": node_id,
                            "type": "unknown",
                            "name": node_id.split(":")[-1],
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to get node details for {node_id}: {e}")
                details.append(
                    {
                        "id": node_id,
                        "type": "unknown",
                        "name": node_id.split(":")[-1],
                    }
                )

        return details

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            The GraphNode if found, None otherwise.
        """
        # Access through adapter's graph_store (temporary)
        return self._traversal_adapter._graph_store.get_node(node_id)

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists in the graph.

        Args:
            node_id: The ID of the node to check.

        Returns:
            True if the node exists, False otherwise.
        """
        # Access through adapter's graph_store (temporary)
        return self._traversal_adapter._graph_store.node_exists(node_id)

    def get_architecture(self, repo_id: str) -> ArchitectureOverview:
        """Get high-level architecture overview of a repository.

        Args:
            repo_id: The repository ID.

        Returns:
            ArchitectureOverview with modules and relationships.

        Raises:
            RuntimeError: If stats adapter is not available.
        """
        if not self._stats_adapter:
            raise RuntimeError("Stats adapter not available for architecture queries")

        # Access through stats adapter's graph_store
        return self._stats_adapter._graph_store.get_architecture(repo_id)

    def get_all_paths(
        self,
        node_id: str,
        edge_types: Optional[List[str]] = None,
        max_depth: int = 4,
    ) -> TraversalResult:
        """Get all paths from a node following specified edge types.

        This method explores all paths from the starting node, useful for
        understanding the complete impact and dependencies of a symbol.

        Args:
            node_id: The ID of the starting node.
            edge_types: List of edge types to follow. If None, uses semantic edges fallback.
            max_depth: Maximum path length (default 4).

        Returns:
            TraversalResult containing all nodes and edges in discovered paths.

        Note:
            For repository-aware edge detection, callers should get available edges
            through GraphRetrieverAdapter.get_available_edge_types() and pass them
            as edge_types parameter.
        """
        if edge_types is None:
            # Use semantic edges as fallback when no specific edges provided
            edge_types = GraphEdgeType.semantic_edges()

        # Note: This requires get_all_paths on the traverser
        # For now, use get_reachable_subgraph as a fallback
        # TODO: Add get_all_paths to TraversalAdapter if needed
        return self.get_reachable_subgraph(
            start_id=node_id,
            max_depth=max_depth,
            allowed_edges=edge_types,
            direction="outgoing",
        )

    def list_files(self, repo_id: str) -> List[str]:
        """List all file paths in a repository.

        Args:
            repo_id: The repository ID.

        Returns:
            List of file paths in the repository.
        """
        # Access through adapter's graph_store (temporary)
        return self._traversal_adapter._graph_store.list_files(repo_id)

    def find_file_by_path(self, repo_id: str, file_path: str) -> List[Dict[str, Any]]:
        """Find file nodes matching a given path.

        Args:
            repo_id: The repository ID.
            file_path: The file path to search for.

        Returns:
            List of matching file node dictionaries with id, file_path, and name.
        """
        results = self._symbol_adapter.get_symbols_by_pattern(
            repo_id=repo_id,
            file_pattern=file_path,
            kind="FILE",
            limit=10,
        )

        return [
            {
                "id": result["id"],
                "file_path": result["file_path"],
                "name": result["name"],
            }
            for result in results
        ]

    def get_file_imports(
        self,
        repo_id: str,
        file_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get files that a given file imports.

        Args:
            repo_id: The repository ID.
            file_id: The node ID of the source file.
            limit: Maximum number of results.

        Returns:
            List of dictionaries with file_path and import info for each import.
        """
        neighbors = self.get_neighbors(
            node_id=file_id,
            edge_types=[GraphEdgeType.IMPORTS.value],
            direction="outgoing",
            limit=limit,
        )

        return [
            {
                "id": n.id,
                "file_path": n.attrs.get("file_path"),
                "name": n.attrs.get("name"),
                "import_statement": f"from {n.attrs.get('file_path', '')} import {n.attrs.get('name', '')}",
            }
            for n in neighbors
        ]

    def get_file_imported_by(
        self,
        repo_id: str,
        file_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get files that import a given file.

        Args:
            repo_id: The repository ID.
            file_id: The node ID of the source file.
            limit: Maximum number of results.

        Returns:
            List of dictionaries with file_path and import info for each importer.
        """
        neighbors = self.get_neighbors(
            node_id=file_id,
            edge_types=[GraphEdgeType.IMPORTS.value],
            direction="incoming",
            limit=limit,
        )

        return [
            {
                "id": n.id,
                "file_path": n.attrs.get("file_path"),
                "name": n.attrs.get("name"),
                "import_statement": f"from {n.attrs.get('file_path', '')} import {n.attrs.get('name', '')}",
            }
            for n in neighbors
        ]
