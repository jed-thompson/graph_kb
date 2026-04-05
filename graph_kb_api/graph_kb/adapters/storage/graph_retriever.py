"""Adapter for neo4j-graphrag GraphRetriever with code analysis queries.

This module wraps neo4j-graphrag's retrieval capabilities for code analysis,
providing methods for entry point discovery, call chain traversal, and
class queries.

The adapter supports two initialization modes:
1. Repository-based (preferred): Uses NodeRepository and EdgeRepository
2. Driver-based (legacy): Uses Neo4j Driver directly for backward compatibility
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from neo4j import Driver
from typing_extensions import LiteralString

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models import AnalysisV2Error
from ...models.base import GraphNode
from ...models.enums import GraphEdgeType, GraphNodeType
from ...querying.models import TraversalEdge, TraversalResult

if TYPE_CHECKING:
    from ...storage.neo4j.edge_repository import EdgeRepository
    from ...storage.neo4j.node_repository import NodeRepository

logger = EnhancedLogger(__name__)


class GraphRetrieverAdapter:
    """Adapter for neo4j-graphrag GraphRetriever with code analysis queries.

    Provides methods for querying the code graph for entry points,
    traversing call chains, finding classes, and exploring graph neighborhoods.

    This adapter supports two initialization modes:
    1. Repository-based (preferred): Pass node_repository and edge_repository
    2. Driver-based (legacy): Pass driver directly for backward compatibility
    """

    def __init__(
        self,
        driver_or_node_repo: Union[Driver, "NodeRepository"],
        edge_repository_or_database: Union["EdgeRepository", str] = "neo4j",
        database: str = "neo4j",
    ):
        """Initialize the adapter with repositories or driver.

        Supports two initialization patterns:

        1. Repository-based (preferred):
           GraphRetrieverAdapter(node_repository, edge_repository, database="neo4j")

        2. Driver-based (legacy, for backward compatibility):
           GraphRetrieverAdapter(driver, database="neo4j")

        Args:
            driver_or_node_repo: Either a NodeRepository instance (preferred)
                                 or a Neo4j Driver (legacy)
            edge_repository_or_database: Either an EdgeRepository instance (when
                                         using repository mode) or database name
                                         string (when using driver mode)
            database: Name of the Neo4j database (used in both modes)
        """
        # Detect initialization mode
        if isinstance(driver_or_node_repo, Driver):
            # Legacy driver-based initialization
            self._driver = driver_or_node_repo
            self._node_repo: Optional["NodeRepository"] = None
            self._edge_repo: Optional["EdgeRepository"] = None
            self._database = edge_repository_or_database if isinstance(edge_repository_or_database, str) else database
            self._use_repositories = False
        else:
            # Repository-based initialization
            self._driver = None
            self._node_repo = driver_or_node_repo
            self._edge_repo = edge_repository_or_database if not isinstance(edge_repository_or_database, str) else None
            self._database = database
            self._use_repositories = self._node_repo is not None and self._edge_repo is not None

            if not self._use_repositories:
                raise AnalysisV2Error(
                    "Repository-based initialization requires both node_repository and edge_repository"
                )

    def get_available_edge_types(self, repo_id: Optional[str]) -> List[str]:
        """Get available edge types for a repository.

        Args:
            repo_id: Repository ID to check

        Returns:
            List of edge type strings that exist in the repository
        """
        if self._use_repositories:
            return self._edge_repo.get_available_edge_types(repo_id)
        else:
            # Fallback to semantic edges for driver-based mode
            return GraphEdgeType.semantic_edges()

    def find_entry_points(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query for entry point symbols.

        Finds functions and methods that match entry point patterns
        (HTTP endpoints, CLI commands, main functions, event handlers).

        Args:
            repo_id: Repository identifier
            folder_path: Optional folder path filter

        Returns:
            List of dictionaries containing symbol id and attrs
        """
        if self._use_repositories:
            return self._find_entry_points_via_repository(repo_id, folder_path)
        else:
            return self._find_entry_points_via_driver(repo_id, folder_path)

    def _find_entry_points_via_repository(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find entry points using EdgeRepository.
        """
        # Type assertion: edge_repo must be non-None in repository mode
        assert self._edge_repo is not None, "Repository mode requires valid edge repository"

        # Use EdgeRepository.find_symbols_by_kind for entry point discovery
        symbols = self._edge_repo.find_symbols_by_kind(
            repo_id=repo_id,
            kinds=["function", "method"],
            folder_path=folder_path,
        )

        # Convert to expected format (attrs may already be dict from repository)
        result = []
        for symbol in symbols:
            attrs = symbol.get("attrs", {})
            # Ensure attrs is serialized as string for backward compatibility
            if isinstance(attrs, dict):
                attrs = json.dumps(attrs)
            result.append({
                "id": symbol["id"],
                "attrs": attrs,
            })
        return result

    def _find_entry_points_via_driver(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find entry points using direct Cypher (legacy mode)."""
        # Type assertion: driver must be non-None in driver mode
        assert self._driver is not None, "Driver mode requires valid driver instance"

        # Build the Cypher query for finding entry points
        cypher = """
            MATCH (s:Symbol {repo_id: $repo_id})
            WHERE s.attrs CONTAINS '"kind": "function"'
               OR s.attrs CONTAINS '"kind": "method"'
        """

        params: Dict[str, Any] = {"repo_id": repo_id}

        # Add folder path filter if provided
        if folder_path:
            cypher += """
               AND s.attrs CONTAINS $folder_path
            """
            params["folder_path"] = folder_path

        cypher += """
            RETURN s.id as id, s.attrs as attrs
        """

        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, params)
            return [{"id": record["id"], "attrs": record["attrs"]} for record in result]

    def traverse_calls(
        self,
        start_id: str,
        max_depth: int = 10,
    ) -> List[Dict[str, Any]]:
        """Traverse CALLS relationships from a starting symbol.

        Uses iterative deepening to avoid memory issues with large call chains.
        Follows the call chain from a starting symbol up to max_depth hops,
        returning all nodes and relationships discovered.

        Args:
            start_id: ID of the starting symbol
            max_depth: Maximum traversal depth

        Returns:
            List of dictionaries containing path nodes and relationships
        """
        if self._use_repositories:
            return self._traverse_calls_via_repository(start_id, max_depth)
        else:
            return self._traverse_calls_via_driver(start_id, max_depth)

    def _traverse_calls_via_repository(
        self,
        start_id: str,
        max_depth: int = 10,
    ) -> List[Dict[str, Any]]:
        """Traverse calls using EdgeRepository.
        """
        # Type assertions: repositories must be non-None in repository mode
        assert self._edge_repo is not None, "Repository mode requires valid edge repository"
        assert self._node_repo is not None, "Repository mode requires valid node repository"

        # Clamp max_depth to repository limits (1-10)
        clamped_depth = max(1, min(max_depth, 10))

        # Use EdgeRepository.traverse_relationships for call chain traversal
        paths = self._edge_repo.traverse_relationships(
            start_id=start_id,
            relationship_types=["CALLS"],
            max_depth=clamped_depth,
            direction="outgoing",
        )

        # Aggregate all nodes and relationships from paths
        all_nodes: Dict[str, Dict[str, Any]] = {}
        all_rels: List[Dict[str, Any]] = []
        seen_edge_keys: set = set()

        # Add start node first
        start_node = self._node_repo.get_by_id(start_id)
        if start_node:
            all_nodes[start_id] = {
                "id": start_node.id,
                "attrs": json.dumps(start_node.attrs) if start_node.attrs else "{}",
                "repo_id": start_node.repo_id,
            }

        # Process paths from repository
        for path in paths:
            # Process nodes
            for node_data in path.get("nodes", []):
                node_id = node_data.get("id")
                if node_id and node_id not in all_nodes:
                    attrs = node_data.get("attrs", {})
                    if isinstance(attrs, dict):
                        attrs = json.dumps(attrs)
                    all_nodes[node_id] = {
                        "id": node_id,
                        "attrs": attrs,
                        "repo_id": node_data.get("repo_id", ""),
                    }

            # Process relationships
            for rel in path.get("relationships", []):
                edge_key = (rel.get("source"), rel.get("target"))
                if edge_key not in seen_edge_keys:
                    all_rels.append({
                        "type": rel.get("type", "CALLS"),
                        "start_id": rel.get("source"),
                        "end_id": rel.get("target"),
                    })
                    seen_edge_keys.add(edge_key)

        # Return in the expected format (single path containing all nodes/rels)
        return [{"nodes": list(all_nodes.values()), "rels": all_rels}]

    def _traverse_calls_via_driver(
        self,
        start_id: str,
        max_depth: int = 10,
    ) -> List[Dict[str, Any]]:
        """Traverse calls using direct Cypher (legacy mode)."""
        # Type assertion: driver must be non-None in driver mode
        assert self._driver is not None, "Driver mode requires valid driver instance"

        all_nodes: Dict[str, Dict[str, Any]] = {}
        all_rels: List[Dict[str, Any]] = []
        seen_edge_keys: set = set()
        current_frontier: set = {start_id}
        seen_ids: set = set()

        with self._driver.session(database=self._database) as session:
            # Get start node
            start_result = session.run(
                "MATCH (s:Symbol {id: $start_id}) RETURN s",
                {"start_id": start_id}
            )
            start_record = start_result.single()
            if start_record:
                node = start_record["s"]
                all_nodes[start_id] = {
                    "id": node.get("id"),
                    "attrs": node.get("attrs"),
                    "repo_id": node.get("repo_id"),
                }
                seen_ids.add(start_id)

            # Iteratively traverse one depth at a time
            for _ in range(max_depth):
                if not current_frontier:
                    break

                # Query for CALLS relationships from current frontier
                query = """
                    UNWIND $frontier_ids AS fid
                    MATCH (start:Symbol {id: fid})-[r:CALLS]->(end:Symbol)
                    WHERE NOT end.id IN $seen_ids
                    RETURN DISTINCT end AS node,
                           start.id AS start_id,
                           end.id AS end_id
                    LIMIT 500
                """

                result = session.run(
                    query,
                    {
                        "frontier_ids": list(current_frontier),
                        "seen_ids": list(seen_ids),
                    }
                )

                next_frontier: set = set()

                for record in result:
                    node = record["node"]
                    node_id = node.get("id")

                    if node_id and node_id not in seen_ids:
                        all_nodes[node_id] = {
                            "id": node_id,
                            "attrs": node.get("attrs"),
                            "repo_id": node.get("repo_id"),
                        }
                        seen_ids.add(node_id)
                        next_frontier.add(node_id)

                    # Add relationship
                    edge_key = (record["start_id"], record["end_id"])
                    if edge_key not in seen_edge_keys:
                        all_rels.append({
                            "type": "CALLS",
                            "start_id": record["start_id"],
                            "end_id": record["end_id"],
                        })
                        seen_edge_keys.add(edge_key)

                current_frontier = next_frontier

        # Return in the expected format (single path containing all nodes/rels)
        return [{"nodes": list(all_nodes.values()), "rels": all_rels}]

    def find_classes(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query for class symbols.

        Finds all class symbols in a repository, optionally filtered by folder.

        Args:
            repo_id: Repository identifier
            folder_path: Optional folder path filter

        Returns:
            List of dictionaries containing symbol id and attrs
        """
        if self._use_repositories:
            return self._find_classes_via_repository(repo_id, folder_path)
        else:
            return self._find_classes_via_driver(repo_id, folder_path)

    def _find_classes_via_repository(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find classes using EdgeRepository."""
        # Type assertion: edge_repo must be non-None in repository mode
        assert self._edge_repo is not None, "Repository mode requires valid edge repository"

        # Use EdgeRepository.find_symbols_by_kind for class discovery
        symbols = self._edge_repo.find_symbols_by_kind(
            repo_id=repo_id,
            kinds=["class"],
            folder_path=folder_path,
        )

        # Convert to expected format
        result = []
        for symbol in symbols:
            attrs = symbol.get("attrs", {})
            if isinstance(attrs, dict):
                attrs = json.dumps(attrs)
            result.append({
                "id": symbol["id"],
                "attrs": attrs,
            })
        return result

    def _find_classes_via_driver(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find classes using direct Cypher (legacy mode)."""
        # Type assertion: driver must be non-None in driver mode
        assert self._driver is not None, "Driver mode requires valid driver instance"

        cypher = """
            MATCH (s:Symbol {repo_id: $repo_id})
            WHERE s.attrs CONTAINS '"kind": "class"'
        """

        params: Dict[str, Any] = {"repo_id": repo_id}

        if folder_path:
            cypher += """
               AND s.attrs CONTAINS $folder_path
            """
            params["folder_path"] = folder_path

        cypher += """
            RETURN s.id as id, s.attrs as attrs
        """

        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, params)
            return [{"id": record["id"], "attrs": record["attrs"]} for record in result]

    def get_reachable_subgraph(
        self,
        start_id: str,
        max_depth: int = 5,
        edge_types: Optional[List[str]] = None,
        direction: str = "outgoing",
        repo_id: Optional[str] = None,
    ) -> TraversalResult:
        """Get all nodes reachable within max_depth hops.

        Uses iterative deepening to avoid memory issues with large graphs.
        Queries one depth level at a time instead of using variable-length paths.

        Args:
            start_id: ID of the starting node
            max_depth: Maximum traversal depth
            edge_types: Optional list of edge types to follow (e.g., ["CALLS", "IMPORTS"])
            direction: Traversal direction - "outgoing", "incoming", or "both"
            repo_id: Repository ID for repository-aware edge detection

        Returns:
            TraversalResult containing discovered nodes, edges, and metadata
        """
        if direction not in ("outgoing", "incoming", "both"):
            raise AnalysisV2Error(
                f"Invalid direction: {direction}. Must be 'outgoing', 'incoming', or 'both'"
            )

        # Use repository-aware edge detection if repo_id is provided and edge_types is None
        if edge_types is None:
            # Use repository-aware edge detection
            edge_types = self.get_available_edge_types(repo_id)

        if self._use_repositories:
            return self._get_reachable_subgraph_via_repository(
                start_id, max_depth, edge_types, direction
            )
        else:
            return self._get_reachable_subgraph_via_driver(
                start_id, max_depth, edge_types, direction
            )

    def _get_reachable_subgraph_via_repository(
        self,
        start_id: str,
        max_depth: int = 5,
        edge_types: Optional[List[str]] = None,
        direction: str = "outgoing",
    ) -> TraversalResult:
        """Get reachable subgraph using EdgeRepository.
        """
        # Type assertions: repositories must be non-None in repository mode
        assert self._edge_repo is not None, "Repository mode requires valid edge repository"
        assert self._node_repo is not None, "Repository mode requires valid node repository"

        # Default edge types for code analysis - use all semantic edges
        if edge_types is None:
            edge_types = GraphEdgeType.semantic_edges()

        # Clamp max_depth to repository limits (1-10)
        clamped_depth = max(1, min(max_depth, 10))

        # Use EdgeRepository.get_reachable_nodes
        nodes, edges = self._edge_repo.get_reachable_nodes(
            start_id=start_id,
            edge_types=edge_types,
            max_depth=clamped_depth,
            direction=direction,
        )

        # Convert edges to TraversalEdge objects
        traversal_edges = []
        for edge in edges:
            traversal_edges.append(TraversalEdge(
                source_id=edge.get("source", ""),
                target_id=edge.get("target", ""),
                edge_type=edge.get("type", ""),
                direction=direction if direction != "both" else "outgoing",
            ))

        # Add start node if not already in results
        start_node = self._node_repo.get_by_id(start_id)
        start_node_in_results = any(n.id == start_id for n in nodes)

        if start_node and not start_node_in_results:
            nodes.insert(0, start_node)

        # Calculate depth statistics
        # Since repository doesn't track depth per node, we estimate based on edges
        node_count_by_depth: Dict[int, int] = {}
        if nodes:
            # Depth 0 is the start node
            node_count_by_depth[0] = 1
            # Remaining nodes are distributed across depths (simplified)
            remaining = len(nodes) - 1
            if remaining > 0:
                node_count_by_depth[1] = remaining

        # Determine if truncated (reached max depth or hit limits)
        is_truncated = len(nodes) >= 1000 or clamped_depth < max_depth

        return TraversalResult(
            nodes=nodes,
            edges=traversal_edges,
            depth_reached=min(clamped_depth, max_depth),
            is_truncated=is_truncated,
            node_count_by_depth=node_count_by_depth,
        )

    def _get_reachable_subgraph_via_driver(
        self,
        start_id: str,
        max_depth: int = 5,
        edge_types: Optional[List[str]] = None,
        direction: str = "outgoing",
    ) -> TraversalResult:
        """Get reachable subgraph using direct Cypher (legacy mode)."""
        # Build edge type filter
        edge_filter = ""
        if edge_types:
            edge_type_str = "|".join(edge_types)
            edge_filter = f":{edge_type_str}"

        # Use iterative deepening to avoid memory explosion
        return self._iterative_traverse(start_id, max_depth, edge_filter, direction, edge_types)

    def _iterative_traverse(
        self,
        start_id: str,
        max_depth: int,
        edge_filter: str,
        direction: str,
        edge_types: Optional[List[str]],
    ) -> TraversalResult:
        """Execute traversal using iterative deepening to avoid memory issues.

        Instead of using variable-length paths which can explode memory usage,
        this queries one depth level at a time, collecting results incrementally.
        """
        # Type assertion: driver must be non-None in driver mode
        assert self._driver is not None, "Driver mode requires valid driver instance"

        nodes: List[GraphNode] = []
        edges: List[TraversalEdge] = []
        seen_node_ids: set = set()
        seen_edge_keys: set = set()
        node_count_by_depth: Dict[int, int] = {}
        max_depth_reached = 0
        is_truncated = False

        # Start with the initial node
        current_frontier: set = {start_id}

        with self._driver.session(database=self._database) as session:
            # Get and add start node first
            start_result = session.run(
                "MATCH (n {id: $start_id}) RETURN n, labels(n) as labels",
                {"start_id": start_id}
            )
            start_record = start_result.single()
            if start_record:
                start_node = start_record["n"]
                attrs = start_node.get("attrs", "{}")
                if isinstance(attrs, str):
                    try:
                        attrs_dict = json.loads(attrs)
                    except json.JSONDecodeError:
                        attrs_dict = {}
                else:
                    attrs_dict = attrs if isinstance(attrs, dict) else {}

                nodes.append(GraphNode(
                    id=start_id,
                    type=GraphNodeType.SYMBOL,
                    repo_id=start_node.get("repo_id", ""),
                    attrs=attrs_dict,
                ))
                seen_node_ids.add(start_id)
                node_count_by_depth[0] = 1

            # Build relationship pattern based on direction
            if direction == "outgoing":
                rel_pattern = f"-[r{edge_filter}]->"
            elif direction == "incoming":
                rel_pattern = f"<-[r{edge_filter}]-"
            else:  # both
                rel_pattern = f"-[r{edge_filter}]-"

            # Iteratively expand one depth at a time
            for depth in range(1, max_depth + 1):
                if not current_frontier:
                    break

                # Query for neighbors of current frontier (single hop)
                # Use LIMIT to prevent memory explosion
                query = f"""
                    UNWIND $frontier_ids AS fid
                    MATCH (start {{id: fid}}){rel_pattern}(neighbor)
                    WHERE NOT neighbor.id IN $seen_ids
                    WITH DISTINCT neighbor,
                         startNode(r).id AS source_id,
                         endNode(r).id AS target_id,
                         type(r) AS rel_type
                    RETURN neighbor AS n, labels(neighbor) AS labels,
                           source_id, target_id, rel_type
                    LIMIT 1000
                """

                # Cast to LiteralString for type safety - query uses parameterized inputs
                result = session.run(
                    cast(LiteralString, query),
                    {
                        "frontier_ids": list(current_frontier),
                        "seen_ids": list(seen_node_ids),
                    }
                )

                next_frontier: set = set()
                depth_node_count = 0
                result_count = 0

                for record in result:
                    result_count += 1
                    node = record["n"]
                    node_id = node.get("id")

                    if node_id and node_id not in seen_node_ids:
                        attrs = node.get("attrs", "{}")
                        if isinstance(attrs, str):
                            try:
                                attrs_dict = json.loads(attrs)
                            except json.JSONDecodeError:
                                attrs_dict = {}
                        else:
                            attrs_dict = attrs if isinstance(attrs, dict) else {}

                        nodes.append(GraphNode(
                            id=node_id,
                            type=GraphNodeType.SYMBOL,
                            repo_id=node.get("repo_id", ""),
                            attrs=attrs_dict,
                        ))
                        seen_node_ids.add(node_id)
                        next_frontier.add(node_id)
                        depth_node_count += 1

                    # Process edge
                    edge_type = record["rel_type"]
                    # Filter by edge types if specified
                    if edge_types and edge_type not in edge_types:
                        continue

                    edge_key = (record["source_id"], record["target_id"], edge_type)
                    if edge_key not in seen_edge_keys:
                        edges.append(TraversalEdge(
                            source_id=record["source_id"],
                            target_id=record["target_id"],
                            edge_type=edge_type,
                            direction=direction if direction != "both" else "outgoing",
                        ))
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

        return TraversalResult(
            nodes=nodes,
            edges=edges,
            depth_reached=max_depth_reached,
            is_truncated=is_truncated,
            node_count_by_depth=node_count_by_depth,
        )
