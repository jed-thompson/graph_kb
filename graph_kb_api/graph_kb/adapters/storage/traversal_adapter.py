"""Adapter for graph traversal operations.

This module implements the TraversalAdapter, which encapsulates graph traversal
logic moved from RecursiveGraphTraverser. The adapter uses repositories exclusively
for database access, following the established adapter pattern.
"""

from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

from neo4j.exceptions import Neo4jError

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.base import GraphNode
from ...models.enums import GraphNodeType
from ...querying.models import TraversalEdge, TraversalResult
from .interfaces import ITraversalAdapter

if TYPE_CHECKING:
    from ...storage.neo4j.edge_repository import EdgeRepository
    from ...storage.neo4j.node_repository import NodeRepository

logger = EnhancedLogger(__name__)


class TraversalAdapter(ITraversalAdapter):
    """Encapsulates graph traversal logic.

    Moves traversal queries from RecursiveGraphTraverser to this adapter,
    ensuring services don't access the driver directly. The adapter uses
    repositories exclusively for database access.
    """

    def __init__(
        self,
        node_repository: "NodeRepository",
        edge_repository: "EdgeRepository",
    ):
        """Initialize the adapter with repositories.

        Args:
            node_repository: NodeRepository instance for node operations
            edge_repository: EdgeRepository instance for edge operations
        """
        self._node_repo = node_repository
        self._edge_repo = edge_repository

    def get_reachable_subgraph(
        self,
        start_id: str,
        max_depth: int = 5,
        allowed_edges: Optional[List[str]] = None,
        direction: str = "outgoing",
        repo_id: Optional[str] = None,
    ) -> TraversalResult:
        """Get all nodes reachable from start within max_depth hops.

        Uses iterative deepening to avoid memory issues. This implementation
        is moved from RecursiveGraphTraverser._cypher_traverse().

        Args:
            start_id: The ID of the starting node.
            max_depth: Maximum traversal depth (default 5, max 30).
            allowed_edges: List of edge types to traverse. If None, uses
                          repository-aware edge detection or defaults.
            direction: "outgoing", "incoming", or "both".
            repo_id: Repository ID for repository-aware edge detection.

        Returns:
            TraversalResult containing all discovered nodes and edges.
        """
        # Clamp max_depth to reasonable bounds
        max_depth = max(1, min(max_depth, 30))

        # Get effective edge types - use repository-aware detection if available
        if allowed_edges is None:
            allowed_edges = self._edge_repo.get_available_edge_types(repo_id)
            logger.debug(f"Using repository-aware edge types for {repo_id}: {allowed_edges}")

        nodes: List[GraphNode] = []
        edges: List[TraversalEdge] = []

        try:
            # Use edge repository's traversal method
            node_records, edge_records, node_count_by_depth, max_depth_reached, is_truncated = \
                self._edge_repo.get_reachable_subgraph(
                    start_id=start_id,
                    max_depth=max_depth,
                    edge_types=allowed_edges,
                    direction=direction,
                )

            # Convert records to domain objects
            for node_record in node_records:
                nodes.append(self._record_to_node(node_record))

            for edge_record in edge_records:
                edge_direction = "outgoing" if direction != "incoming" else "incoming"
                edges.append(
                    TraversalEdge(
                        source_id=edge_record['source_id'],
                        target_id=edge_record['target_id'],
                        edge_type=edge_record['rel_type'],
                        direction=edge_direction,
                    )
                )

            return TraversalResult(
                nodes=nodes,
                edges=edges,
                depth_reached=max_depth_reached,
                is_truncated=is_truncated,
                node_count_by_depth=node_count_by_depth,
            )

        except Neo4jError as e:
            logger.error("Cypher traversal query failed: %s", e)
            raise

    def get_bidirectional_neighborhood(
        self,
        node_id: str,
        max_depth: int = 5,
        allowed_edges: Optional[List[str]] = None,
        repo_id: Optional[str] = None,
    ) -> TraversalResult:
        """Get both callers (incoming) and callees (outgoing) of a symbol.

        This method performs bidirectional traversal to gather the complete
        neighborhood of a symbol, including both what it calls and what calls it.

        Args:
            node_id: The ID of the central node.
            max_depth: Maximum traversal depth in each direction.
            allowed_edges: List of edge types to traverse. If None, uses
                          repository-aware edge detection or defaults.
            repo_id: Repository ID for repository-aware edge detection.

        Returns:
            TraversalResult containing nodes and edges from both directions.
        """
        # Get effective edge types - use repository-aware detection if available
        if allowed_edges is None:
            allowed_edges = self._edge_repo.get_available_edge_types(repo_id)
            logger.debug(f"Using repository-aware edge types for {repo_id}: {allowed_edges}")

        # Get outgoing neighbors (callees, imports, etc.)
        outgoing_result = self.get_reachable_subgraph(
            start_id=node_id,
            max_depth=max_depth,
            allowed_edges=allowed_edges,
            direction="outgoing",
            repo_id=repo_id,
        )

        # Get incoming neighbors (callers, importers, etc.)
        incoming_result = self.get_reachable_subgraph(
            start_id=node_id,
            max_depth=max_depth,
            allowed_edges=allowed_edges,
            direction="incoming",
            repo_id=repo_id,
        )

        # Merge results, deduplicating nodes
        return self._merge_results(outgoing_result, incoming_result)

    def _merge_results(
        self,
        result1: TraversalResult,
        result2: TraversalResult,
    ) -> TraversalResult:
        """Merge two traversal results, deduplicating nodes and edges."""
        seen_node_ids: Set[str] = set()
        seen_edge_keys: Set[Tuple[str, str, str]] = set()
        merged_nodes: List[GraphNode] = []
        merged_edges: List[TraversalEdge] = []
        merged_depth_counts: Dict[int, int] = {}

        # Process nodes from both results
        for node in result1.nodes + result2.nodes:
            if node.id not in seen_node_ids:
                merged_nodes.append(node)
                seen_node_ids.add(node.id)

        # Process edges from both results
        for edge in result1.edges + result2.edges:
            edge_key = (edge.source_id, edge.target_id, edge.edge_type)
            if edge_key not in seen_edge_keys:
                merged_edges.append(edge)
                seen_edge_keys.add(edge_key)

        # Merge depth counts
        for depth, count in result1.node_count_by_depth.items():
            merged_depth_counts[depth] = merged_depth_counts.get(depth, 0) + count
        for depth, count in result2.node_count_by_depth.items():
            merged_depth_counts[depth] = merged_depth_counts.get(depth, 0) + count

        return TraversalResult(
            nodes=merged_nodes,
            edges=merged_edges,
            depth_reached=max(result1.depth_reached, result2.depth_reached),
            is_truncated=result1.is_truncated or result2.is_truncated,
            node_count_by_depth=merged_depth_counts,
        )

    def _get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID using the node repository."""
        return self._node_repo.get_by_id(node_id)

    def _record_to_node(self, record) -> GraphNode:
        """Convert a Neo4j record to a GraphNode."""
        node_data = record["n"]
        labels = record["labels"]

        # Determine node type from labels
        node_type = GraphNodeType.SYMBOL  # default
        for label in labels:
            try:
                node_type = GraphNodeType(label)
                break
            except ValueError:
                continue

        # Use repository's deserialization method
        attrs = self._node_repo._deserialize_attrs(node_data.get("attrs", "{}"))

        return GraphNode(
            id=node_data.get("id", ""),
            type=node_type,
            repo_id=node_data.get("repo_id", ""),
            attrs=attrs,
            summary=node_data.get("summary"),
        )
