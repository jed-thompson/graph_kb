"""Protocol interfaces for storage adapters.

This module defines protocol interfaces for adapters that bridge the service
layer and the storage facade. Adapters encapsulate query patterns and data
transformation logic, ensuring services don't access the driver directly.
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ...querying.models import TraversalResult


@runtime_checkable
class ITraversalAdapter(Protocol):
    """Interface for graph traversal operations.

    This adapter encapsulates graph traversal logic, moving it from services
    to a dedicated adapter layer. Services use this adapter instead of
    accessing the driver directly.
    """

    def __init__(
        self,
        node_repository: Any,
        edge_repository: Any
    ) -> None:
        """Initialize the traversal adapter.

        Args:
            node_repository: NodeRepository instance for node operations
            edge_repository: EdgeRepository instance for edge operations
        """
        ...

    def get_reachable_subgraph(
        self,
        start_id: str,
        max_depth: int,
        allowed_edges: List[str],
        direction: str,
    ) -> TraversalResult:
        """Get all nodes reachable from start within max_depth hops.

        Args:
            start_id: The ID of the starting node.
            max_depth: Maximum traversal depth.
            allowed_edges: List of edge types to traverse.
            direction: "outgoing", "incoming", or "both".

        Returns:
            TraversalResult containing all discovered nodes and edges.
        """
        ...

    def get_bidirectional_neighborhood(
        self,
        node_id: str,
        max_depth: int,
        allowed_edges: List[str],
    ) -> TraversalResult:
        """Get both callers (incoming) and callees (outgoing) of a symbol.

        Args:
            node_id: The ID of the central node.
            max_depth: Maximum traversal depth in each direction.
            allowed_edges: List of edge types to traverse.

        Returns:
            TraversalResult containing nodes and edges from both directions.
        """
        ...


@runtime_checkable
class ISymbolQueryAdapter(Protocol):
    """Interface for symbol query operations.

    This adapter encapsulates symbol search patterns, moving them from services
    to a dedicated adapter layer. Services use this adapter instead of
    accessing the driver directly.
    """

    def __init__(self, graph_store: Any) -> None:
        """Initialize the symbol query adapter.

        Args:
            graph_store: The graph store instance to use for queries.
        """
        ...

    def get_symbols_by_pattern(
        self,
        repo_id: str,
        name_pattern: Optional[str],
        file_pattern: Optional[str],
        kind: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Get symbols matching specified patterns.

        Args:
            repo_id: The repository ID.
            name_pattern: Regex pattern for symbol name.
            file_pattern: Regex pattern for file path.
            kind: Symbol kind filter (function, class, method).
            limit: Maximum number of results.

        Returns:
            List of dictionaries with symbol information.
        """
        ...

    def search_symbols_by_name(
        self,
        repo_id: str,
        name: str,
    ) -> List[str]:
        """Search for symbols by name in the graph.

        Args:
            repo_id: The repository ID.
            name: The symbol name to search for.

        Returns:
            List of matching symbol IDs.
        """
        ...


@runtime_checkable
class IDirectoryAdapter(Protocol):
    """Interface for directory/file operations.

    This adapter encapsulates directory and file query patterns.
    """

    def __init__(self, graph_store: Any) -> None:
        """Initialize the directory adapter.

        Args:
            graph_store: The graph store instance to use for queries.
        """
        ...

    def get_directory_summary(
        self,
        repo_id: str,
        directory_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Get summary information about a directory.

        Args:
            repo_id: The repository ID.
            directory_name: The directory name to query.

        Returns:
            Dictionary with directory summary information, or None if not found.
        """
        ...
