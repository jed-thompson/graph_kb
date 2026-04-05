"""Edge repository for Neo4j graph operations.

This module provides the EdgeRepository class for handling all edge/relationship
operations in the Neo4j graph database.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from neo4j.exceptions import Neo4jError

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.base import GraphEdge, GraphNode
from ...models.enums import GraphEdgeType, GraphNodeType
from .connection import SessionManager
from .queries import EdgeQueries, SymbolQueries

logger = EnhancedLogger(__name__)


class EdgeRepository:
    """Repository for graph edge operations.

    This class handles all edge/relationship operations including:
    - Creating edges of all types (CONTAINS, CALLS, IMPORTS, EXTENDS, etc.)
    - Retrieving neighbors with direction support
    - Finding paths between nodes
    - Getting reachable nodes within a depth limit

    All operations use the SessionManager for database access and
    reference queries from the centralized queries module.
    """

    def __init__(self, session_manager: SessionManager):
        """Initialize the EdgeRepository.

        Args:
            session_manager: SessionManager instance for database operations.
        """
        self._session_manager = session_manager

    def create(self, edge: GraphEdge) -> None:
        """Create an edge between two nodes in the graph.

        Creates a relationship with the appropriate type based on edge_type.
        The edge will have an ID and optional attributes.

        Args:
            edge: The GraphEdge to create.

        Raises:
            Neo4jError: If edge creation fails.
        """
        edge_type = edge.edge_type.value
        query = EdgeQueries.CREATE_EDGE.format(edge_type=edge_type)

        try:
            with self._session_manager.session() as session:
                session.run(
                    query,
                    from_id=edge.from_node,
                    to_id=edge.to_node,
                    edge_id=edge.id,
                    attrs=self._serialize_attrs(edge.attrs),
                )
        except Neo4jError as e:
            logger.error(f"Failed to create edge {edge.id}: {e}")
            raise

    def exists(self, from_id: str, to_id: str, edge_type: GraphEdgeType) -> bool:
        """Check if an edge exists between two nodes.

        Args:
            from_id: Source node ID.
            to_id: Target node ID.
            edge_type: Type of edge to check.

        Returns:
            True if the edge exists, False otherwise.

        Raises:
            Neo4jError: If the check fails.
        """
        query = EdgeQueries.EDGE_EXISTS.format(edge_type=edge_type.value)

        try:
            with self._session_manager.session() as session:
                result = session.run(query, from_id=from_id, to_id=to_id)
                record = result.single()
                return record["exists"] if record else False
        except Neo4jError as e:
            logger.error(f"Failed to check edge existence: {e}")
            raise

    def get_neighbors(
        self,
        node_id: str,
        edge_types: List[str],
        direction: str = "outgoing",
        limit: int = 100,
    ) -> List[GraphNode]:
        """Get neighboring nodes connected by specified edge types.

        Args:
            node_id: The ID of the source node.
            edge_types: List of edge type names to traverse.
            direction: "outgoing", "incoming", or "both".
            limit: Maximum number of neighbors to return.

        Returns:
            List of neighboring GraphNode objects.

        Raises:
            Neo4jError: If retrieval fails.
            ValueError: If direction is invalid.
        """
        if not edge_types:
            return []

        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(
                f"Invalid direction: {direction}. Must be 'outgoing', 'incoming', or 'both'"
            )

        edge_pattern = "|".join(edge_types)

        if direction == "outgoing":
            query = EdgeQueries.GET_NEIGHBORS_OUTGOING.format(edge_pattern=edge_pattern)
        elif direction == "incoming":
            query = EdgeQueries.GET_NEIGHBORS_INCOMING.format(edge_pattern=edge_pattern)
        else:
            query = EdgeQueries.GET_NEIGHBORS_BOTH.format(edge_pattern=edge_pattern)

        try:
            with self._session_manager.session() as session:
                result = session.run(query, id=node_id, limit=limit)
                return [self._record_to_node(record) for record in result]
        except Neo4jError as e:
            logger.error(f"Failed to get neighbors for {node_id}: {e}")
            raise

    def find_path(
        self,
        from_id: str,
        to_id: str,
        edge_types: Optional[List[str]] = None,
        max_hops: int = 5,
    ) -> Optional[List[str]]:
        """Find shortest path between two nodes.

        Args:
            from_id: ID of the source node.
            to_id: ID of the target node.
            edge_types: Optional list of edge types to traverse.
                If None, any edge type is allowed.
            max_hops: Maximum path length (1-10).

        Returns:
            List of node IDs in the path (starting with from_id, ending with to_id),
            or None if no path exists.

        Raises:
            Neo4jError: If path finding fails.
            ValueError: If max_hops is out of range.
        """
        if max_hops < 1 or max_hops > 10:
            raise ValueError(f"max_hops must be between 1 and 10, got {max_hops}")

        if edge_types:
            edge_pattern = "|".join(edge_types)
            query = EdgeQueries.FIND_PATH_WITH_TYPES.format(
                edge_pattern=edge_pattern,
                max_hops=max_hops,
            )
        else:
            query = EdgeQueries.FIND_PATH_ANY_TYPE.format(max_hops=max_hops)

        try:
            with self._session_manager.session() as session:
                result = session.run(query, from_id=from_id, to_id=to_id)
                record = result.single()
                if record:
                    return record["path"]
                return None
        except Neo4jError as e:
            logger.error(f"Failed to find path from {from_id} to {to_id}: {e}")
            raise

    def get_reachable_nodes(
        self,
        start_id: str,
        edge_types: List[str],
        max_depth: int,
        direction: str = "outgoing",
    ) -> Tuple[List[GraphNode], List[Dict[str, Any]]]:
        """Get all nodes reachable within max_depth hops.

        Args:
            start_id: The ID of the starting node.
            edge_types: List of edge type names to traverse.
            max_depth: Maximum number of hops (1-10).
            direction: "outgoing", "incoming", or "both".

        Returns:
            Tuple of (nodes, edges) where:
            - nodes: List of reachable GraphNode objects
            - edges: List of edge dictionaries with source, target, type

        Raises:
            Neo4jError: If retrieval fails.
            ValueError: If max_depth is out of range or direction is invalid.
        """
        if not edge_types:
            return [], []

        if max_depth < 1 or max_depth > 10:
            raise ValueError(f"max_depth must be between 1 and 10, got {max_depth}")

        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(
                f"Invalid direction: {direction}. Must be 'outgoing', 'incoming', or 'both'"
            )

        edge_pattern = "|".join(edge_types)

        if direction == "outgoing":
            rel_pattern = f"-[r:{edge_pattern}*1..{max_depth}]->"
        elif direction == "incoming":
            rel_pattern = f"<-[r:{edge_pattern}*1..{max_depth}]-"
        else:
            rel_pattern = f"-[r:{edge_pattern}*1..{max_depth}]-"

        query = EdgeQueries.GET_REACHABLE_NODES.format(rel_pattern=rel_pattern)

        try:
            with self._session_manager.session() as session:
                result = session.run(query, start_id=start_id)

                nodes: List[GraphNode] = []
                all_edges: List[Dict[str, Any]] = []
                seen_node_ids: set = set()
                seen_edge_keys: set = set()

                for record in result:
                    node = self._record_to_node(record)
                    if node.id not in seen_node_ids:
                        nodes.append(node)
                        seen_node_ids.add(node.id)

                    for edge in record["edges"]:
                        edge_key = (edge["source"], edge["target"], edge["type"])
                        if edge_key not in seen_edge_keys:
                            all_edges.append(edge)
                            seen_edge_keys.add(edge_key)

                return nodes, all_edges
        except Neo4jError as e:
            logger.error(f"Failed to get reachable nodes from {start_id}: {e}")
            raise

    def get_reachable_subgraph(
        self,
        start_id: str,
        max_depth: int,
        edge_types: List[str],
        direction: str = "outgoing",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[int, int], int, bool]:
        """Get detailed traversal information for reachable subgraph.

        This method performs iterative deepening traversal and returns detailed
        information about nodes, edges, and depth distribution.

        Args:
            start_id: Starting node ID
            max_depth: Maximum traversal depth
            edge_types: List of edge types to traverse
            direction: "outgoing", "incoming", or "both"

        Returns:
            Tuple of (nodes, edges, node_count_by_depth, max_depth_reached, is_truncated)
            - nodes: List of node records with 'n' and 'labels' keys
            - edges: List of edge records with 'source_id', 'target_id', 'rel_type' keys
            - node_count_by_depth: Dict mapping depth to node count
            - max_depth_reached: Maximum depth actually reached
            - is_truncated: Whether results were truncated
        """
        from ...storage.queries.traversal_queries import TraversalQueries

        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []
        seen_node_ids: set = set()
        seen_edge_keys: set = set()
        node_count_by_depth: Dict[int, int] = {}
        max_depth_reached = 0
        is_truncated = False

        # Start with the initial node
        current_frontier: set = {start_id}

        try:
            with self._session_manager.session() as session:
                # Add start node first
                start_result = session.run(
                    "MATCH (n {id: $id}) RETURN n, labels(n) as labels",
                    {"id": start_id}
                )
                start_record = start_result.single()
                if start_record:
                    nodes.append({
                        'n': start_record['n'],
                        'labels': start_record['labels']
                    })
                    seen_node_ids.add(start_id)
                    node_count_by_depth[0] = 1

                # Iteratively expand one depth at a time
                for depth in range(1, max_depth + 1):
                    if not current_frontier:
                        break

                    # Build relationship pattern
                    rel_pattern = TraversalQueries.build_rel_pattern(
                        edge_types=edge_types,
                        direction=direction,
                    )

                    # Use query from TraversalQueries
                    query = TraversalQueries.ITERATIVE_NEIGHBORS.format(
                        rel_pattern=rel_pattern
                    )

                    result = session.run(
                        query,
                        frontier_ids=list(current_frontier),
                        seen_ids=list(seen_node_ids),
                    )

                    next_frontier: set = set()
                    depth_node_count = 0
                    result_count = 0

                    for record in result:
                        result_count += 1

                        # Store node record
                        node_record = {
                            'n': record['n'],
                            'labels': record['labels']
                        }

                        node_id = record['n'].get('id', '')

                        # Deduplicate nodes
                        if node_id not in seen_node_ids:
                            nodes.append(node_record)
                            seen_node_ids.add(node_id)
                            next_frontier.add(node_id)
                            depth_node_count += 1

                        # Process edge
                        edge_key = (
                            record["source_id"],
                            record["target_id"],
                            record["rel_type"],
                        )
                        if edge_key not in seen_edge_keys:
                            edges.append({
                                'source_id': record["source_id"],
                                'target_id': record["target_id"],
                                'rel_type': record["rel_type"],
                            })
                            seen_edge_keys.add(edge_key)

                    if depth_node_count > 0:
                        node_count_by_depth[depth] = depth_node_count
                        max_depth_reached = depth

                    # Check if we hit the limit (truncated)
                    if result_count >= 1000:
                        is_truncated = True

                    current_frontier = next_frontier

                # Also mark as truncated if we reached max depth with remaining frontier
                if current_frontier and max_depth_reached >= max_depth:
                    is_truncated = True

                return nodes, edges, node_count_by_depth, max_depth_reached, is_truncated

        except Neo4jError as e:
            logger.error(f"Failed to get reachable subgraph from {start_id}: {e}")
            raise

    def delete(self, from_id: str, to_id: str, edge_type: GraphEdgeType) -> None:
        """Delete an edge between two nodes.

        Args:
            from_id: Source node ID.
            to_id: Target node ID.
            edge_type: Type of edge to delete.

        Raises:
            Neo4jError: If deletion fails.
        """
        query = f"""
            MATCH (a {{id: $from_id}})-[r:{edge_type.value}]->(b {{id: $to_id}})
            DELETE r
        """

        try:
            with self._session_manager.session() as session:
                session.run(query, from_id=from_id, to_id=to_id)
        except Neo4jError as e:
            logger.error(f"Failed to delete edge from {from_id} to {to_id}: {e}")
            raise

    def find_symbols_by_kind(
        self,
        repo_id: str,
        kinds: List[str],
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find symbols by kind (function, method, class, etc.).

        This method supports the V2 analysis adapters for entry point discovery
        and symbol filtering operations. Uses COALESCE with APOC fallback to
        support both migrated nodes (with top-level properties) and unmigrated
        nodes (with attrs JSON).

        Args:
            repo_id: Repository ID to search within.
            kinds: List of symbol kinds to filter by (e.g., ["function", "method"]).
            folder_path: Optional folder path to filter symbols by location.

        Returns:
            List of dictionaries with 'id' and 'attrs' keys for matching symbols.

        Raises:
            Neo4jError: If the query fails.
        """
        if not kinds:
            return []

        kind_conditions = SymbolQueries.build_kind_conditions(kinds)

        if folder_path:
            query = SymbolQueries.FIND_BY_KIND_WITH_PATH.format(
                kind_conditions=kind_conditions
            )
            params = {
                "repo_id": repo_id,
                "folder_path": folder_path,  # For top-level file_path property
                "folder_pattern": f'"{folder_path}',  # For attrs JSON fallback
            }
        else:
            query = SymbolQueries.FIND_BY_KIND.format(
                kind_conditions=kind_conditions
            )
            params = {"repo_id": repo_id}

        try:
            with self._session_manager.session() as session:
                result = session.run(query, **params)
                symbols = []
                for record in result:
                    symbols.append({
                        "id": record["id"],
                        "attrs": self._deserialize_attrs(record["attrs"]),
                    })
                return symbols
        except Neo4jError as e:
            logger.error(f"Failed to find symbols by kind in {repo_id}: {e}")
            raise

    def traverse_relationships(
        self,
        start_id: str,
        relationship_types: List[str],
        max_depth: int = 10,
        direction: str = "outgoing",
    ) -> List[Dict[str, Any]]:
        """Traverse relationships and return path information.

        This method supports the V2 analysis adapters for call chain traversal
        and data flow tracing operations.

        Args:
            start_id: ID of the starting node.
            relationship_types: List of relationship types to traverse
                (e.g., ["CALLS", "IMPORTS"]).
            max_depth: Maximum traversal depth (1-10, default 10).
            direction: "outgoing", "incoming", or "both" (default "outgoing").

        Returns:
            List of path dictionaries, each containing:
            - 'nodes': List of node dicts with 'id' and 'attrs'
            - 'relationships': List of relationship dicts with 'source', 'target', 'type'

        Raises:
            Neo4jError: If the query fails.
            ValueError: If max_depth is out of range or direction is invalid.
        """
        if not relationship_types:
            return []

        if max_depth < 1 or max_depth > 10:
            raise ValueError(f"max_depth must be between 1 and 10, got {max_depth}")

        if direction not in ("outgoing", "incoming", "both"):
            raise ValueError(
                f"Invalid direction: {direction}. Must be 'outgoing', 'incoming', or 'both'"
            )

        rel_pattern = SymbolQueries.build_rel_pattern(
            relationship_types, max_depth, direction
        )
        query = SymbolQueries.TRAVERSE_RELATIONSHIPS.format(rel_pattern=rel_pattern)

        try:
            with self._session_manager.session() as session:
                result = session.run(query, start_id=start_id)
                paths = []
                for record in result:
                    # Parse nodes - each node is a dict with id and attrs
                    nodes = []
                    for node_data in record["nodes"]:
                        nodes.append({
                            "id": node_data["id"],
                            "attrs": self._deserialize_attrs(node_data.get("attrs")),
                        })

                    paths.append({
                        "nodes": nodes,
                        "relationships": record["relationships"],
                    })
                return paths
        except Neo4jError as e:
            logger.error(f"Failed to traverse relationships from {start_id}: {e}")
            raise

    def _record_to_node(self, record) -> GraphNode:
        """Convert a Neo4j record to a GraphNode.

        Args:
            record: Neo4j record with 'n' (node) and 'labels' fields.

        Returns:
            GraphNode instance.
        """
        node_data = record["n"]
        labels = record["labels"]

        # Determine node type from labels
        node_type = GraphNodeType.SYMBOL  # Default
        for label in labels:
            try:
                node_type = GraphNodeType(label)
                break
            except ValueError:
                continue

        attrs = self._deserialize_attrs(node_data.get("attrs", "{}"))

        # For Chunk nodes, attrs are stored directly on the node
        if node_type == GraphNodeType.CHUNK:
            attrs = {
                "file_path": node_data.get("file_path"),
                "start_line": node_data.get("start_line"),
                "end_line": node_data.get("end_line"),
                "language": node_data.get("language"),
                "content": node_data.get("content"),
                "symbols_defined": self._parse_symbols_list(
                    node_data.get("symbols_defined", "")
                ),
                "symbols_referenced": self._parse_symbols_list(
                    node_data.get("symbols_referenced", "")
                ),
            }

        return GraphNode(
            id=node_data.get("id", ""),
            type=node_type,
            repo_id=node_data.get("repo_id", ""),
            attrs=attrs,
            summary=node_data.get("summary"),
        )

    def _serialize_attrs(self, attrs: Dict[str, Any]) -> str:
        """Serialize attributes dictionary to JSON string.

        Args:
            attrs: Dictionary of attributes.

        Returns:
            JSON string representation.
        """
        return json.dumps(attrs)

    def _deserialize_attrs(self, attrs_str: Optional[str]) -> Dict[str, Any]:
        """Deserialize attributes from JSON string.

        Args:
            attrs_str: JSON string of attributes.

        Returns:
            Dictionary of attributes.
        """
        if not attrs_str:
            return {}
        try:
            return json.loads(attrs_str)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_available_edge_types(self, repo_id: str) -> List[str]:
        """Get only the relationship types that actually exist in this repository.

        This method queries the Neo4j database to find which relationship types
        are actually present for the given repository, avoiding Neo4j warnings
        about unknown relationship types.

        Args:
            repo_id: The repository ID to check

        Returns:
            List of relationship type strings that exist in the repository

        Note:
            This eliminates Neo4j warnings like "Unknown relationship type: IMPLEMENTS"
            for Python repositories that don't have interface implementations.
        """
        try:
            with self._session_manager.session() as session:
                # Query to find all relationship types that exist for this repo
                # We check both directions and filter by repo_id on nodes
                result = session.run(
                    EdgeQueries.GET_AVAILABLE_EDGE_TYPES,
                    {"repo_id": repo_id}
                )

                existing_types = [record["rel_type"] for record in result]

                # Filter semantic_edges to only include existing types
                all_semantic = GraphEdgeType.semantic_edges()
                available_edges = [edge_type for edge_type in all_semantic if edge_type in existing_types]

                # Always include CONTAINS as it's structural and should exist
                if GraphEdgeType.CONTAINS.value not in available_edges and GraphEdgeType.CONTAINS.value in all_semantic:
                    available_edges.append(GraphEdgeType.CONTAINS.value)

                logger.debug(
                    f"Detected available edges for repo {repo_id}",
                    data={
                        "repo_id": repo_id,
                        "available_edges": available_edges,
                        "filtered_out": [e for e in all_semantic if e not in available_edges]
                    }
                )

                return available_edges

        except Exception as e:
            # Fallback to core edge types that are most likely to exist
            # This ensures the system continues working even if the query fails
            logger.warning(f"Failed to detect available edge types for repo {repo_id}: {e}")

            # Return conservative set of edge types that exist in most repositories
            fallback_edges = [
                GraphEdgeType.CALLS.value,
                GraphEdgeType.IMPORTS.value,
                GraphEdgeType.EXTENDS.value,
                GraphEdgeType.CONTAINS.value,
                GraphEdgeType.DECORATES.value,
            ]

            return fallback_edges

    def _parse_symbols_list(self, value) -> list:
        """Parse symbols_defined or symbols_referenced from string or list.

        Args:
            value: Either a string (comma-separated) or a list.

        Returns:
            List of symbol strings.
        """
        if value is None:
            return []
        if isinstance(value, list):
            return [s.strip() if isinstance(s, str) else str(s) for s in value if s]
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return []
