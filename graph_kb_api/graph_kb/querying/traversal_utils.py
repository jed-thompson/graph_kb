"""Traversal utilities for graph query results.

This module provides utilities for processing graph traversal results,
including:

- PathExtractor: Extract and format paths from TraversalResult objects
- EdgeGrouper: Organize and filter edges by type and direction

These utilities convert raw graph data into structured, human-readable
representations suitable for display, analysis, or further processing.
"""

from collections import defaultdict
from typing import Any, Dict, List, Set

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from .models import TraversalEdge, TraversalResult

logger = EnhancedLogger(__name__)


class PathExtractor:
    """Extracts structured paths from graph traversal results.

    This utility converts TraversalResult objects (containing flat lists of
    nodes and edges) into structured path representations suitable for
    display, analysis, or further processing.

    Example:
        >>> extractor = PathExtractor()
        >>> paths = extractor.extract_paths_from_traversal(
        ...     traversal_result=result,
        ...     start_id="repo:main",
        ...     direction="outgoing",
        ...     max_paths=50
        ... )
        >>> # Returns: [[{name, file_path, line_number, node_id}, ...], ...]
    """

    @staticmethod
    def extract_paths_from_traversal(
        traversal_result: TraversalResult,
        start_id: str,
        direction: str,
        max_paths: int = 100
    ) -> List[List[Dict[str, Any]]]:
        """Extract all paths from a traversal result using depth-first search.

        Converts a flat TraversalResult (nodes + edges) into a list of paths,
        where each path is a sequence of nodes from start to leaf nodes.

        Args:
            traversal_result: TraversalResult containing nodes and edges
            start_id: Starting node ID for path extraction
            direction: "outgoing" (follow source->target) or "incoming" (follow target->source)
            max_paths: Maximum number of paths to return (prevents overwhelming output)

        Returns:
            List of paths, where each path is a list of node dictionaries with:
                - name: Symbol name
                - file_path: File location
                - line_number: Line number in file
                - node_id: Unique node identifier

        Example:
            >>> paths = PathExtractor.extract_paths_from_traversal(result, "main", "outgoing")
            >>> # Returns paths like:
            >>> # [
            >>> #   [{"name": "main", ...}, {"name": "authenticate", ...}, {"name": "validate", ...}],
            >>> #   [{"name": "main", ...}, {"name": "process", ...}]
            >>> # ]
        """
        if not traversal_result.nodes or not traversal_result.edges:
            logger.debug("Empty traversal result, returning no paths")
            return []

        # Build adjacency map from edges based on direction
        adjacency = PathExtractor._build_adjacency_map(
            traversal_result.edges,
            direction
        )

        # Build node lookup map for quick access
        node_map = {node.id: node for node in traversal_result.nodes}

        # Extract all paths using DFS
        path_ids = PathExtractor._extract_path_ids_dfs(
            start_id=start_id,
            adjacency=adjacency,
            max_paths=max_paths
        )

        # Format paths with node details
        formatted_paths = PathExtractor._format_paths_with_details(
            path_ids=path_ids,
            node_map=node_map
        )

        logger.debug(
            f"Extracted {len(formatted_paths)} paths from traversal",
            data={
                'start_id': start_id,
                'direction': direction,
                'node_count': len(traversal_result.nodes),
                'edge_count': len(traversal_result.edges)
            }
        )

        return formatted_paths

    @staticmethod
    def _build_adjacency_map(
        edges: List[Any],
        direction: str
    ) -> Dict[str, List[str]]:
        """Build adjacency map from edges based on traversal direction.

        Args:
            edges: List of TraversalEdge objects
            direction: "outgoing" or "incoming"

        Returns:
            Dictionary mapping node_id -> list of neighbor node_ids
        """
        adjacency = {}

        for edge in edges:
            if direction == "outgoing":
                # For outgoing, follow source -> target
                if edge.source_id not in adjacency:
                    adjacency[edge.source_id] = []
                adjacency[edge.source_id].append(edge.target_id)
            else:
                # For incoming, follow target -> source (reverse direction)
                if edge.target_id not in adjacency:
                    adjacency[edge.target_id] = []
                adjacency[edge.target_id].append(edge.source_id)

        return adjacency

    @staticmethod
    def _extract_path_ids_dfs(
        start_id: str,
        adjacency: Dict[str, List[str]],
        max_paths: int
    ) -> List[List[str]]:
        """Extract all paths from start node using depth-first search.

        Args:
            start_id: Starting node ID
            adjacency: Adjacency map (node_id -> [neighbor_ids])
            max_paths: Maximum number of paths to extract

        Returns:
            List of paths, where each path is a list of node IDs
        """
        all_paths = []
        visited: Set[str] = set()

        def dfs(current_id: str, path: List[str]):
            """Recursive DFS to find all paths."""
            if len(all_paths) >= max_paths:
                return

            # Add current node to path
            path.append(current_id)

            # Get neighbors
            neighbors = adjacency.get(current_id, [])

            if not neighbors:
                # Leaf node - this is a complete path
                all_paths.append(path[:])
            else:
                # Continue exploring unvisited neighbors
                for neighbor_id in neighbors:
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        dfs(neighbor_id, path)
                        visited.remove(neighbor_id)

            path.pop()

        # Start DFS from start_id
        visited.add(start_id)
        dfs(start_id, [])

        return all_paths[:max_paths]

    @staticmethod
    def _format_paths_with_details(
        path_ids: List[List[str]],
        node_map: Dict[str, Any]
    ) -> List[List[Dict[str, Any]]]:
        """Format paths with detailed node information.

        Args:
            path_ids: List of paths (each path is a list of node IDs)
            node_map: Dictionary mapping node_id -> GraphNode

        Returns:
            List of formatted paths with node details
        """
        formatted_paths = []

        for path in path_ids:
            formatted_path = []

            for node_id in path:
                node = node_map.get(node_id)

                if node:
                    # Node found in map - extract details
                    formatted_path.append({
                        'name': node.attrs.get('name', node_id.split(':')[-1]),
                        'file_path': node.attrs.get('file_path'),
                        'line_number': node.attrs.get('line_number'),
                        'node_id': node_id
                    })
                else:
                    # Node not in map - use ID as fallback
                    formatted_path.append({
                        'name': node_id.split(':')[-1],
                        'file_path': None,
                        'line_number': None,
                        'node_id': node_id
                    })

            if formatted_path:
                formatted_paths.append(formatted_path)

        return formatted_paths

    @staticmethod
    def format_path_as_text(path: List[Dict[str, Any]]) -> str:
        """Format a path as human-readable text.

        Args:
            path: List of node dictionaries with name, file_path, line_number

        Returns:
            Formatted string representation of the path

        Example:
            >>> path = [
            ...     {"name": "main", "file_path": "app.py", "line_number": 10},
            ...     {"name": "process", "file_path": "core.py", "line_number": 45}
            ... ]
            >>> PathExtractor.format_path_as_text(path)
            'main (app.py:10) → process (core.py:45)'
        """
        parts = []

        for node in path:
            name = node.get('name', 'unknown')
            file_path = node.get('file_path')
            line_number = node.get('line_number')

            if file_path and line_number:
                parts.append(f"{name} ({file_path}:{line_number})")
            elif file_path:
                parts.append(f"{name} ({file_path})")
            else:
                parts.append(name)

        return " → ".join(parts)

    @staticmethod
    def get_path_statistics(paths: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Calculate statistics about extracted paths.

        Args:
            paths: List of paths from extract_paths_from_traversal

        Returns:
            Dictionary with path statistics:
                - total_paths: Number of paths
                - avg_path_length: Average path length
                - max_path_length: Longest path length
                - min_path_length: Shortest path length
                - unique_nodes: Number of unique nodes across all paths
        """
        if not paths:
            return {
                'total_paths': 0,
                'avg_path_length': 0,
                'max_path_length': 0,
                'min_path_length': 0,
                'unique_nodes': 0
            }

        path_lengths = [len(path) for path in paths]
        unique_nodes = set()

        for path in paths:
            for node in path:
                unique_nodes.add(node.get('node_id'))

        return {
            'total_paths': len(paths),
            'avg_path_length': sum(path_lengths) / len(path_lengths),
            'max_path_length': max(path_lengths),
            'min_path_length': min(path_lengths),
            'unique_nodes': len(unique_nodes)
        }


class EdgeGrouper:
    """Utilities for grouping and organizing edges from traversal results.

    This class provides methods for organizing edges by direction, type,
    and node relationships, which is commonly needed when building context
    packets, visualizations, or analyzing graph structure.

    Example:
        >>> grouper = EdgeGrouper()
        >>> outgoing, incoming = grouper.group_edges_by_direction(edges)
        >>> calls_edges = grouper.filter_edges_by_type(edges, "CALLS")
    """

    @staticmethod
    def group_edges_by_direction(
        edges: List[TraversalEdge]
    ) -> tuple[Dict[str, List[TraversalEdge]], Dict[str, List[TraversalEdge]]]:
        """Group edges into outgoing and incoming maps by node.

        This is useful for quickly finding all edges going out from or coming
        into a specific node, which is common when building context packets
        or analyzing node neighborhoods.

        Args:
            edges: List of TraversalEdge objects

        Returns:
            Tuple of (outgoing_map, incoming_map) where:
                - outgoing_map: Dict[source_id -> List[edges from that source]]
                - incoming_map: Dict[target_id -> List[edges to that target]]

        Example:
            >>> outgoing, incoming = EdgeGrouper.group_edges_by_direction(edges)
            >>> # Get all edges going out from node "main"
            >>> main_calls = outgoing.get("repo:main", [])
            >>> # Get all edges coming into node "validate"
            >>> validate_callers = incoming.get("repo:validate", [])
        """
        outgoing_edges: Dict[str, List[TraversalEdge]] = defaultdict(list)
        incoming_edges: Dict[str, List[TraversalEdge]] = defaultdict(list)

        for edge in edges:
            outgoing_edges[edge.source_id].append(edge)
            incoming_edges[edge.target_id].append(edge)

        return dict(outgoing_edges), dict(incoming_edges)

    @staticmethod
    def filter_edges_by_type(
        edges: List[TraversalEdge],
        edge_type: str
    ) -> List[TraversalEdge]:
        """Filter edges to only those of a specific type.

        Args:
            edges: List of TraversalEdge objects
            edge_type: Edge type to filter for (e.g., "CALLS", "IMPORTS")

        Returns:
            List of edges matching the specified type

        Example:
            >>> calls_edges = EdgeGrouper.filter_edges_by_type(edges, "CALLS")
            >>> imports_edges = EdgeGrouper.filter_edges_by_type(edges, "IMPORTS")
        """
        return [edge for edge in edges if edge.edge_type == edge_type]

    @staticmethod
    def group_edges_by_type(
        edges: List[TraversalEdge]
    ) -> Dict[str, List[TraversalEdge]]:
        """Group edges by their type.

        Args:
            edges: List of TraversalEdge objects

        Returns:
            Dictionary mapping edge_type -> List[edges of that type]

        Example:
            >>> by_type = EdgeGrouper.group_edges_by_type(edges)
            >>> calls = by_type.get("CALLS", [])
            >>> imports = by_type.get("IMPORTS", [])
        """
        grouped: Dict[str, List[TraversalEdge]] = defaultdict(list)

        for edge in edges:
            grouped[edge.edge_type].append(edge)

        return dict(grouped)

    @staticmethod
    def get_outgoing_edges_by_type(
        node_id: str,
        edges: List[TraversalEdge],
        edge_type: str
    ) -> List[TraversalEdge]:
        """Get all outgoing edges of a specific type from a node.

        Convenience method that combines direction and type filtering.

        Args:
            node_id: Source node ID
            edges: List of TraversalEdge objects
            edge_type: Edge type to filter for

        Returns:
            List of outgoing edges of the specified type from the node

        Example:
            >>> # Get all functions that "main" calls
            >>> calls = EdgeGrouper.get_outgoing_edges_by_type(
            ...     "repo:main", edges, "CALLS"
            ... )
        """
        return [
            edge for edge in edges
            if edge.source_id == node_id and edge.edge_type == edge_type
        ]

    @staticmethod
    def get_incoming_edges_by_type(
        node_id: str,
        edges: List[TraversalEdge],
        edge_type: str
    ) -> List[TraversalEdge]:
        """Get all incoming edges of a specific type to a node.

        Convenience method that combines direction and type filtering.

        Args:
            node_id: Target node ID
            edges: List of TraversalEdge objects
            edge_type: Edge type to filter for

        Returns:
            List of incoming edges of the specified type to the node

        Example:
            >>> # Get all functions that call "validate"
            >>> callers = EdgeGrouper.get_incoming_edges_by_type(
            ...     "repo:validate", edges, "CALLS"
            ... )
        """
        return [
            edge for edge in edges
            if edge.target_id == node_id and edge.edge_type == edge_type
        ]

    @staticmethod
    def get_unique_edge_types(edges: List[TraversalEdge]) -> List[str]:
        """Get list of unique edge types present in the edge list.

        Args:
            edges: List of TraversalEdge objects

        Returns:
            Sorted list of unique edge type strings

        Example:
            >>> types = EdgeGrouper.get_unique_edge_types(edges)
            >>> # Returns: ["CALLS", "IMPORTS", "EXTENDS"]
        """
        edge_types: Set[str] = set()
        for edge in edges:
            edge_types.add(edge.edge_type)
        return sorted(list(edge_types))

    @staticmethod
    def deduplicate_edges(edges: List[TraversalEdge]) -> List[TraversalEdge]:
        """Remove duplicate edges based on (source, target, type).

        Useful when merging edges from multiple traversal results.

        Args:
            edges: List of TraversalEdge objects (may contain duplicates)

        Returns:
            List of unique edges

        Example:
            >>> unique_edges = EdgeGrouper.deduplicate_edges(all_edges)
        """
        seen_keys: Set[tuple[str, str, str]] = set()
        unique_edges: List[TraversalEdge] = []

        for edge in edges:
            edge_key = (edge.source_id, edge.target_id, edge.edge_type)
            if edge_key not in seen_keys:
                seen_keys.add(edge_key)
                unique_edges.append(edge)

        return unique_edges
