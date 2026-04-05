"""GraphQuerier for Neo4j visualization queries.

This module provides the GraphQuerier class that executes Neo4j queries
to fetch graph data for different visualization types.

Supports recursive multi-hop traversal for deeper graph exploration.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, cast

if TYPE_CHECKING:
    from typing import LiteralString

    from ..storage.graph_store import Neo4jGraphStore
else:
    # Python 3.10 compatibility - LiteralString added in 3.11
    LiteralString = str

from graph_kb_api.config import settings
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.enums import GraphEdgeType, GraphNodeType
from ..models.visualization import VisEdge, VisGraph, VisNode
from ..storage.queries import VisualizationQueries

logger = EnhancedLogger(__name__)

# Default traversal depth from settings (used for calls/dependencies)
DEFAULT_TRAVERSAL_DEPTH = settings.max_depth

# Maximum depth allowed for visualization queries (balance between completeness and performance)
MAX_VISUALIZATION_DEPTH = 30


class GraphQuerier:
    """Queries Neo4j for visualization data.

    Uses the existing Neo4jGraphStore driver but adds visualization-specific
    queries that return VisGraph structures.
    """

    def __init__(self, graph_store: "Neo4jGraphStore"):
        """Initialize the GraphQuerier.

        Args:
            graph_store: The Neo4jGraphStore instance to use for queries.
        """
        self.graph_store = graph_store
        self._config = graph_store._config

    def query_architecture(
        self, repo_id: str, folder_path: Optional[str] = None, limit: int = 500
    ) -> VisGraph:
        """Query File nodes grouped by directory to show module structure.

        Since Directory nodes may not be explicitly stored, this query:
        1. Fetches File nodes for the repo
        2. Extracts unique directory paths from file paths
        3. Creates synthetic directory nodes for visualization
        4. Creates CONTAINS edges between directories and files

        Args:
            repo_id: Repository identifier
            folder_path: Optional path prefix to filter results
            limit: Maximum number of nodes to return

        Returns:
            VisGraph with directory and file nodes
        """
        # Query all File nodes for this repo (not just those directly under Repo)
        query = VisualizationQueries.ARCHITECTURE_FILES

        nodes: Dict[str, VisNode] = {}
        edges: List[VisEdge] = []
        directories: Set[str] = set[str]()

        try:
            with self.graph_store._session_manager.session() as session:
                result = session.run(cast(LiteralString, query), repo_id=repo_id)

                for record in result:
                    attrs = self.graph_store._deserialize_attrs(record["attrs"])
                    file_path = attrs.get("file_path", "")

                    # Apply folder path filter if specified
                    if folder_path and not file_path.startswith(folder_path):
                        continue

                    # Create file node
                    file_id = record["id"]
                    file_name = file_path.split("/")[-1] if file_path else file_id
                    file_node = VisNode(
                        id=file_id,
                        label=file_name,
                        node_type=GraphNodeType.FILE,
                        full_path=file_path,
                        metadata=attrs,
                    )
                    nodes[file_id] = file_node

                    # Extract directory paths
                    parts = file_path.split("/")
                    if len(parts) > 1:
                        # Build directory hierarchy
                        for i in range(1, len(parts)):
                            dir_path = "/".join(parts[:i])
                            directories.add(dir_path)

            # Create directory nodes
            for dir_path in directories:
                dir_name = dir_path.split("/")[-1] if "/" in dir_path else dir_path
                dir_id = f"{repo_id}:dir:{dir_path}"
                dir_node = VisNode(
                    id=dir_id,
                    label=dir_name,
                    node_type=GraphNodeType.DIRECTORY,
                    full_path=dir_path,
                    metadata={"type": "directory"},
                )
                nodes[dir_id] = dir_node

            # Create CONTAINS edges between directories and their children
            for dir_path in directories:
                dir_id = f"{repo_id}:dir:{dir_path}"
                parent_parts = dir_path.split("/")

                # Find parent directory
                if len(parent_parts) > 1:
                    parent_path = "/".join(parent_parts[:-1])
                    parent_id = f"{repo_id}:dir:{parent_path}"
                    if parent_id in nodes:
                        edges.append(
                            VisEdge(
                                source=parent_id,
                                target=dir_id,
                                edge_type=GraphEdgeType.CONTAINS,
                            )
                        )

            # Create CONTAINS edges from directories to files
            for file_id, file_node in list[tuple[str, VisNode]](nodes.items()):
                if file_node.node_type == GraphNodeType.FILE:
                    file_path = file_node.full_path
                    parts = file_path.split("/")
                    if len(parts) > 1:
                        parent_dir = "/".join(parts[:-1])
                        parent_id = f"{repo_id}:dir:{parent_dir}"
                        if parent_id in nodes:
                            edges.append(
                                VisEdge(
                                    source=parent_id,
                                    target=file_id,
                                    edge_type=GraphEdgeType.CONTAINS,
                                )
                            )

            # Apply limit - ensure we include parent directories for included files
            # to maintain hierarchical structure with valid edges
            file_nodes = [n for n in nodes.values() if n.node_type == GraphNodeType.FILE]

            # Take a subset of files
            file_limit = min(len(file_nodes), limit // 2)
            selected_files = file_nodes[:file_limit]

            # Collect all parent directories needed for selected files
            needed_dirs: Set[str] = set[str]()
            for file_node in selected_files:
                parts = file_node.full_path.split("/")
                for i in range(1, len(parts)):
                    dir_path = "/".join(parts[:i])
                    dir_id = f"{repo_id}:dir:{dir_path}"
                    if dir_id in nodes:
                        needed_dirs.add(dir_id)

            # Get the directory nodes we need
            selected_dirs = [nodes[dir_id] for dir_id in needed_dirs if dir_id in nodes]

            # Combine and apply final limit
            node_list = selected_dirs + selected_files
            if len(node_list) > limit:
                # If over limit, reduce files to fit
                excess = len(node_list) - limit
                node_list = selected_dirs + selected_files[:-excess] if excess < len(selected_files) else selected_dirs[:limit]

            node_ids = {n.id for n in node_list}

            # Filter edges to only include those between included nodes
            filtered_edges = [
                e for e in edges if e.source in node_ids and e.target in node_ids
            ]

            return VisGraph(nodes=node_list, edges=filtered_edges)

        except Exception as e:
            logger.error(f"Failed to query architecture for repo {repo_id}: {e}")
            return VisGraph()

    def path_exists(self, repo_id: str, folder_path: str) -> bool:
        """Check if any nodes exist with the given path prefix.

        Args:
            repo_id: Repository identifier
            folder_path: Path prefix to check

        Returns:
            True if nodes exist with this path prefix
        """
        query = VisualizationQueries.PATH_EXISTS

        try:
            with self.graph_store._session_manager.session() as session:
                # Use a pattern that matches the folder_path in attrs
                result = session.run(
                    cast(LiteralString, query),
                    repo_id=repo_id,
                    path_pattern=f'"file_path": "{folder_path}',
                )
                record = result.single()
                return record["exists"] if record else False
        except Exception as e:
            logger.error(f"Failed to check path existence for {folder_path}: {e}")
            return False


    def query_calls(
        self, repo_id: str, folder_path: Optional[str] = None, limit: int = 5000,
        max_depth: Optional[int] = None, entry_point: Optional[str] = None,
        symbol_kinds: Optional[List[str]] = None
    ) -> VisGraph:
        """Query Symbol nodes and CALLS edges with recursive traversal.

        Uses variable-length path matching to traverse call chains up to max_depth hops,
        providing a much deeper view of the call graph than single-hop queries.

        Args:
            repo_id: Repository identifier
            folder_path: Optional path prefix to filter symbols
            limit: Maximum number of edges to return
            max_depth: Maximum traversal depth (defaults to settings.max_depth)
            entry_point: Optional symbol name/pattern to start traversal from
            symbol_kinds: Optional list of symbol kinds to include (e.g., ['function', 'method', 'class'])

        Returns:
            VisGraph with symbol nodes and CALLS edges
        """
        if max_depth is None:
            max_depth = DEFAULT_TRAVERSAL_DEPTH

        # Clamp depth to reasonable bounds for visualization (higher than before)
        max_depth = max(1, min(max_depth, MAX_VISUALIZATION_DEPTH))

        # Build query based on whether we have an entry point
        query = VisualizationQueries.build_calls_query(max_depth, entry_point, limit)

        nodes: Dict[str, VisNode] = {}
        edges: List[VisEdge] = []
        seen_edges: Set[tuple] = set[tuple[Any, ...]]()

        try:
            with self.graph_store._session_manager.session() as session:
                params = {
                    "repo_id": repo_id,
                    "limit": limit * 3  # Fetch more to account for filtering
                }
                if entry_point:
                    params["entry_pattern"] = f'"name": "{entry_point}'

                result = session.run(cast(LiteralString, query), **params)

                edge_count = 0
                for record in result:
                    if edge_count >= limit:
                        break

                    from_attrs = self.graph_store._deserialize_attrs(
                        record["from_attrs"]
                    )
                    to_attrs = self.graph_store._deserialize_attrs(record["to_attrs"])

                    from_path = from_attrs.get("file_path", "")
                    to_path = to_attrs.get("file_path", "")

                    # Apply folder path filter if specified
                    if folder_path:
                        if not from_path.startswith(
                            folder_path
                        ) and not to_path.startswith(folder_path):
                            continue

                    # Apply symbol kind filter if specified
                    if symbol_kinds:
                        from_kind = from_attrs.get("kind", "")
                        to_kind = to_attrs.get("kind", "")
                        if from_kind not in symbol_kinds and to_kind not in symbol_kinds:
                            continue

                    from_id = record["from_id"]
                    to_id = record["to_id"]

                    # Deduplicate edges
                    edge_key = (from_id, to_id)
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    # Create source node if not exists
                    if from_id not in nodes:
                        from_name = from_attrs.get("name", from_id.split(":")[-1])
                        nodes[from_id] = VisNode(
                            id=from_id,
                            label=from_name,
                            node_type=GraphNodeType.SYMBOL,
                            full_path=from_path,
                            metadata=from_attrs,
                            symbol_kind=from_attrs.get("kind"),
                        )

                    # Create target node if not exists
                    if to_id not in nodes:
                        to_name = to_attrs.get("name", to_id.split(":")[-1])
                        nodes[to_id] = VisNode(
                            id=to_id,
                            label=to_name,
                            node_type=GraphNodeType.SYMBOL,
                            full_path=to_path,
                            metadata=to_attrs,
                            symbol_kind=to_attrs.get("kind"),
                        )

                    # Create CALLS edge
                    edges.append(
                        VisEdge(
                            source=from_id,
                            target=to_id,
                            edge_type=GraphEdgeType.CALLS,
                        )
                    )
                    edge_count += 1

            logger.info(
                f"query_calls: Found {len(nodes)} nodes and {len(edges)} edges "
                f"with max_depth={max_depth} for repo {repo_id}"
            )
            return VisGraph(nodes=list[VisNode](nodes.values()), edges=edges)

        except Exception as e:
            logger.error(f"Failed to query calls for repo {repo_id}: {e}")
            return VisGraph()

    def query_call_chain(
        self, repo_id: str, start_symbol: str, direction: str = "outgoing",
        max_depth: int = 15, limit: int = 500
    ) -> VisGraph:
        """Query a specific call chain starting from a symbol.

        Traces calls either outgoing (what does this symbol call?) or incoming
        (what calls this symbol?) to visualize specific execution paths.

        Args:
            repo_id: Repository identifier
            start_symbol: Name or pattern of the starting symbol
            direction: "outgoing" (calls from) or "incoming" (calls to)
            max_depth: Maximum traversal depth
            limit: Maximum number of edges to return

        Returns:
            VisGraph with the call chain
        """
        max_depth = max(1, min(max_depth, MAX_VISUALIZATION_DEPTH))

        # Use centralized query
        query = VisualizationQueries.build_call_chain_query(max_depth, direction)

        return self._execute_call_query(query, repo_id, start_symbol, limit, max_depth, direction)

    def query_hotspots(
        self, repo_id: str, folder_path: Optional[str] = None,
        top_n: int = 50, min_connections: int = 5
    ) -> VisGraph:
        """Query the most connected symbols (hotspots) in the codebase.

        Identifies symbols with the most incoming/outgoing CALLS edges,
        which often represent core functionality or potential refactoring targets.

        Args:
            repo_id: Repository identifier
            folder_path: Optional path prefix to filter
            top_n: Number of top symbols to include
            min_connections: Minimum connections to be considered a hotspot

        Returns:
            VisGraph with hotspot symbols and their immediate connections
        """
        # Find symbols with most connections
        query = VisualizationQueries.HOTSPOTS_HIGH_DEGREE

        nodes: Dict[str, VisNode] = {}
        edges: List[VisEdge] = []
        seen_edges: Set[tuple] = set[tuple[Any, ...]]()
        hotspot_ids: Set[str] = set[str]()

        try:
            with self.graph_store._session_manager.session() as session:
                # First, get the hotspot symbols
                result = session.run(
                    cast(LiteralString, query),
                    repo_id=repo_id,
                    min_connections=min_connections,
                    top_n=top_n
                )

                for record in result:
                    attrs = self.graph_store._deserialize_attrs(record["attrs"]) or {}
                    file_path = attrs.get("file_path", "")

                    # Apply folder filter
                    if folder_path and not file_path.startswith(folder_path):
                        continue

                    symbol_id = record["id"]
                    hotspot_ids.add(symbol_id)

                    symbol_name = attrs.get("name", symbol_id.split(":")[-1])
                    # Add connection count to label for visibility
                    label = f"{symbol_name} ({record['total']})"

                    nodes[symbol_id] = VisNode(
                        id=symbol_id,
                        label=label,
                        node_type=GraphNodeType.SYMBOL,
                        full_path=file_path,
                        metadata={
                            **attrs,
                            "outgoing_calls": record["outgoing"],
                            "incoming_calls": record["incoming"],
                            "total_connections": record["total"],
                        },
                        symbol_kind=attrs.get("kind"),
                    )

                # Now get edges between hotspots
                if hotspot_ids:
                    edge_query = VisualizationQueries.HOTSPOTS_EDGES
                    edge_result = session.run(
                        cast(LiteralString, edge_query),
                        repo_id=repo_id,
                        hotspot_ids=list[str](hotspot_ids)
                    )

                    for record in edge_result:
                        from_id = record["from_id"]
                        to_id = record["to_id"]
                        edge_key = (from_id, to_id)
                        if edge_key not in seen_edges:
                            edges.append(VisEdge(
                                source=from_id,
                                target=to_id,
                                edge_type=GraphEdgeType.CALLS,
                            ))
                            seen_edges.add(edge_key)

            logger.info(
                f"query_hotspots: Found {len(nodes)} hotspot symbols and {len(edges)} edges "
                f"for repo {repo_id}"
            )
            return VisGraph(nodes=list[VisNode](nodes.values()), edges=edges)

        except Exception as e:
            logger.error(f"Failed to query hotspots for repo {repo_id}: {e}")
            return VisGraph()

    def _execute_call_query(
        self, query: str, repo_id: str, symbol_pattern: str,
        limit: int, max_depth: int, direction: str
    ) -> VisGraph:
        """Execute a call chain query and build the VisGraph."""
        nodes: Dict[str, VisNode] = {}
        edges: List[VisEdge] = []
        seen_edges: Set[tuple] = set[tuple[Any, ...]]()

        try:
            with self.graph_store._session_manager.session() as session:
                result = session.run(
                    cast(LiteralString, query),
                    repo_id=repo_id,
                    symbol_pattern=f'"name": "{symbol_pattern}',
                    limit=limit * 2
                )

                edge_count = 0
                for record in result:
                    if edge_count >= limit:
                        break

                    from_attrs = self.graph_store._deserialize_attrs(record["from_attrs"]) or {}
                    to_attrs = self.graph_store._deserialize_attrs(record["to_attrs"]) or {}

                    from_id = record["from_id"]
                    to_id = record["to_id"]

                    edge_key = (from_id, to_id)
                    if edge_key in seen_edges:
                        continue
                    seen_edges.add(edge_key)

                    # Create nodes
                    if from_id not in nodes:
                        from_name = from_attrs.get("name", from_id.split(":")[-1])
                        nodes[from_id] = VisNode(
                            id=from_id,
                            label=from_name,
                            node_type=GraphNodeType.SYMBOL,
                            full_path=from_attrs.get("file_path", ""),
                            metadata=from_attrs,
                            symbol_kind=from_attrs.get("kind"),
                        )

                    if to_id not in nodes:
                        to_name = to_attrs.get("name", to_id.split(":")[-1])
                        nodes[to_id] = VisNode(
                            id=to_id,
                            label=to_name,
                            node_type=GraphNodeType.SYMBOL,
                            full_path=to_attrs.get("file_path", ""),
                            metadata=to_attrs,
                            symbol_kind=to_attrs.get("kind"),
                        )

                    edges.append(VisEdge(
                        source=from_id,
                        target=to_id,
                        edge_type=GraphEdgeType.CALLS,
                    ))
                    edge_count += 1

            logger.info(
                f"query_call_chain ({direction}): Found {len(nodes)} nodes and {len(edges)} edges "
                f"with max_depth={max_depth} for symbol '{symbol_pattern}'"
            )
            return VisGraph(nodes=list[VisNode](nodes.values()), edges=edges)

        except Exception as e:
            logger.error(f"Failed to query call chain for {symbol_pattern}: {e}")
            return VisGraph()

    def query_dependencies(
        self, repo_id: str, folder_path: Optional[str] = None, limit: int = 2000,
        max_depth: Optional[int] = None
    ) -> VisGraph:
        """Query File nodes and IMPORTS edges with recursive traversal.

        Uses variable-length path matching to traverse import chains up to max_depth hops,
        showing transitive dependencies between files.

        Args:
            repo_id: Repository identifier
            folder_path: Optional path prefix to filter files
            limit: Maximum number of nodes to return
            max_depth: Maximum traversal depth (defaults to settings.max_depth)

        Returns:
            VisGraph with file nodes and IMPORTS edges
        """
        if max_depth is None:
            max_depth = DEFAULT_TRAVERSAL_DEPTH

        # Clamp depth to reasonable bounds for visualization
        max_depth = max(1, min(max_depth, MAX_VISUALIZATION_DEPTH))

        # Use centralized query with variable depth
        query = VisualizationQueries.build_dependencies_query(max_depth)

        nodes: Dict[str, VisNode] = {}
        edges: List[VisEdge] = []
        seen_edges: Set[tuple] = set[tuple[Any, ...]]()

        try:
            with self.graph_store._session_manager.session() as session:
                result = session.run(
                    cast(LiteralString, query),
                    repo_id=repo_id,
                    limit=limit * 3
                )

                for record in result:
                    from_attrs = self.graph_store._deserialize_attrs(
                        record["from_attrs"]
                    )
                    to_attrs = self.graph_store._deserialize_attrs(record["to_attrs"])

                    from_path = from_attrs.get("file_path", "")
                    to_path = to_attrs.get("file_path", "")

                    # Apply folder path filter if specified
                    if folder_path:
                        if not from_path.startswith(
                            folder_path
                        ) and not to_path.startswith(folder_path):
                            continue

                    from_id = record["from_id"]
                    to_id = record["to_id"]

                    # Create source file node if not exists
                    if from_id not in nodes:
                        from_name = from_path.split("/")[-1] if from_path else from_id
                        nodes[from_id] = VisNode(
                            id=from_id,
                            label=from_name,
                            node_type=GraphNodeType.FILE,
                            full_path=from_path,
                            metadata=from_attrs,
                        )

                    # Create target file node if not exists
                    if to_id not in nodes:
                        to_name = to_path.split("/")[-1] if to_path else to_id
                        nodes[to_id] = VisNode(
                            id=to_id,
                            label=to_name,
                            node_type=GraphNodeType.FILE,
                            full_path=to_path,
                            metadata=to_attrs,
                        )

                    # Create IMPORTS edge (deduplicated)
                    edge_key = (from_id, to_id)
                    if edge_key not in seen_edges:
                        edges.append(
                            VisEdge(
                                source=from_id,
                                target=to_id,
                                edge_type=GraphEdgeType.IMPORTS,
                            )
                        )
                        seen_edges.add(edge_key)

                    # Check node limit
                    if len(nodes) >= limit:
                        break

            # Filter edges to only include those between included nodes
            node_ids = set(nodes.keys())
            filtered_edges = [
                e for e in edges if e.source in node_ids and e.target in node_ids
            ]

            logger.info(
                f"query_dependencies: Found {len(nodes)} nodes and {len(filtered_edges)} edges "
                f"with max_depth={max_depth} for repo {repo_id}"
            )
            return VisGraph(nodes=list(nodes.values()), edges=filtered_edges)

        except Exception as e:
            logger.error(f"Failed to query dependencies for repo {repo_id}: {e}")
            return VisGraph()

    def query_full(
        self, repo_id: str, folder_path: Optional[str] = None, limit: int = 500
    ) -> VisGraph:
        """Query all node types and edge types for comprehensive view.

        Combines results from architecture, calls, and dependencies queries.

        Args:
            repo_id: Repository identifier
            folder_path: Optional path prefix to filter
            limit: Maximum number of nodes to return

        Returns:
            VisGraph with all node and edge types
        """
        # Calculate proportional limits for each query type
        arch_limit = limit // 3
        calls_limit = limit // 3
        deps_limit = limit - arch_limit - calls_limit

        # Get architecture (directories and files)
        arch_graph = self.query_architecture(repo_id, folder_path, arch_limit)

        # Get call relationships
        calls_graph = self.query_calls(repo_id, folder_path, calls_limit)

        # Get dependency relationships
        deps_graph = self.query_dependencies(repo_id, folder_path, deps_limit)

        # Merge all graphs
        all_nodes: Dict[str, VisNode] = {}
        all_edges: List[VisEdge] = []
        seen_edges: Set[tuple] = set[tuple[Any, ...]]()

        # Add nodes from all graphs
        for graph in [arch_graph, calls_graph, deps_graph]:
            for node in graph.nodes:
                if node.id not in all_nodes:
                    all_nodes[node.id] = node

            for edge in graph.edges:
                edge_key = (edge.source, edge.target, edge.edge_type.value)
                if edge_key not in seen_edges:
                    all_edges.append(edge)
                    seen_edges.add(edge_key)

        # Apply final limit
        node_list = list[VisNode](all_nodes.values())[:limit]
        node_ids = {n.id for n in node_list}

        # Filter edges to only include those between included nodes
        filtered_edges = [
            e for e in all_edges if e.source in node_ids and e.target in node_ids
        ]

        return VisGraph(nodes=node_list, edges=filtered_edges)

    def query_comprehensive(
        self, repo_id: str, folder_path: Optional[str] = None, limit: int = 1000
    ) -> VisGraph:
        """Query ALL nodes and ALL edge types in a single unified graph.

        This creates a comprehensive visualization showing:
        - Repo node as the root
        - Directory hierarchy with CONTAINS edges
        - File nodes with CONTAINS edges from directories
        - Symbol nodes (functions, classes, methods) with CONTAINS edges to files
        - All relationship edges: CALLS, IMPORTS, IMPLEMENTS, EXTENDS, USES, DECORATES

        Args:
            repo_id: Repository identifier
            folder_path: Optional path prefix to filter
            limit: Maximum number of nodes to return

        Returns:
            VisGraph with complete repository structure
        """
        nodes: Dict[str, VisNode] = {}
        edges: List[VisEdge] = []
        seen_edges: Set[tuple] = set[tuple[Any, ...]]()

        try:
            with self.graph_store._session_manager.session() as session:
                # 1. Get the Repo node
                repo_query = VisualizationQueries.ARCHITECTURE_REPO
                result = session.run(cast(LiteralString, repo_query), repo_id=repo_id)
                for record in result:
                    attrs = self.graph_store._deserialize_attrs(record["attrs"]) or {}
                    repo_node = VisNode(
                        id=record["id"],
                        label=repo_id,
                        node_type=GraphNodeType.REPO,
                        full_path="",
                        metadata=attrs,
                    )
                    nodes[record["id"]] = repo_node

                # 2. Get all File nodes
                file_query = VisualizationQueries.ARCHITECTURE_FILES
                result = session.run(cast(LiteralString, file_query), repo_id=repo_id)
                directories: Set[str] = set()

                for record in result:
                    attrs = self.graph_store._deserialize_attrs(record["attrs"]) or {}
                    file_path = attrs.get("file_path", "")

                    # Apply folder path filter
                    if folder_path and not file_path.startswith(folder_path):
                        continue

                    file_name = file_path.split("/")[-1] if file_path else record["id"]
                    file_node = VisNode(
                        id=record["id"],
                        label=file_name,
                        node_type=GraphNodeType.FILE,
                        full_path=file_path,
                        metadata=attrs,
                    )
                    nodes[record["id"]] = file_node

                    # Collect directory paths
                    parts = file_path.split("/")
                    for i in range(1, len(parts)):
                        dir_path = "/".join(parts[:i])
                        directories.add(dir_path)

                # 3. Create Directory nodes
                for dir_path in directories:
                    dir_name = dir_path.split("/")[-1] if "/" in dir_path else dir_path
                    dir_id = f"{repo_id}:dir:{dir_path}"
                    dir_node = VisNode(
                        id=dir_id,
                        label=dir_name,
                        node_type=GraphNodeType.DIRECTORY,
                        full_path=dir_path,
                        metadata={"type": "directory"},
                    )
                    nodes[dir_id] = dir_node

                # 4. Get all Symbol nodes
                symbol_query = VisualizationQueries.ARCHITECTURE_SYMBOLS
                result = session.run(cast(LiteralString, symbol_query), repo_id=repo_id)

                for record in result:
                    attrs = self.graph_store._deserialize_attrs(record["attrs"]) or {}
                    file_path = attrs.get("file_path", "")

                    # Apply folder path filter
                    if folder_path and not file_path.startswith(folder_path):
                        continue

                    symbol_name = attrs.get("name", record["id"].split(":")[-1])
                    symbol_kind = attrs.get("kind", "symbol")
                    symbol_node = VisNode(
                        id=record["id"],
                        label=symbol_name,
                        node_type=GraphNodeType.SYMBOL,
                        full_path=file_path,
                        metadata=attrs,
                        symbol_kind=symbol_kind,
                    )
                    nodes[record["id"]] = symbol_node

                # 5. Create CONTAINS edges (Repo -> Directory, Directory -> Directory, Directory -> File)
                # Repo to top-level directories
                repo_node_id = next((n.id for n in nodes.values() if n.node_type == GraphNodeType.REPO), None)
                if repo_node_id:
                    top_level_dirs = {d for d in directories if "/" not in d}
                    for dir_path in top_level_dirs:
                        dir_id = f"{repo_id}:dir:{dir_path}"
                        if dir_id in nodes:
                            edge_key = (repo_node_id, dir_id, GraphEdgeType.CONTAINS.value)
                            if edge_key not in seen_edges:
                                edges.append(VisEdge(
                                    source=repo_node_id,
                                    target=dir_id,
                                    edge_type=GraphEdgeType.CONTAINS,
                                ))
                                seen_edges.add(edge_key)

                # Directory to subdirectory edges
                for dir_path in directories:
                    dir_id = f"{repo_id}:dir:{dir_path}"
                    parts = dir_path.split("/")
                    if len(parts) > 1:
                        parent_path = "/".join(parts[:-1])
                        parent_id = f"{repo_id}:dir:{parent_path}"
                        if parent_id in nodes and dir_id in nodes:
                            edge_key = (parent_id, dir_id, GraphEdgeType.CONTAINS.value)
                            if edge_key not in seen_edges:
                                edges.append(VisEdge(
                                    source=parent_id,
                                    target=dir_id,
                                    edge_type=GraphEdgeType.CONTAINS,
                                ))
                                seen_edges.add(edge_key)

                # Directory to file edges
                for node_id, node in list(nodes.items()):
                    if node.node_type == GraphNodeType.FILE:
                        parts = node.full_path.split("/")
                        if len(parts) > 1:
                            parent_dir = "/".join(parts[:-1])
                            parent_id = f"{repo_id}:dir:{parent_dir}"
                            if parent_id in nodes:
                                edge_key = (parent_id, node_id, GraphEdgeType.CONTAINS.value)
                                if edge_key not in seen_edges:
                                    edges.append(VisEdge(
                                        source=parent_id,
                                        target=node_id,
                                        edge_type=GraphEdgeType.CONTAINS,
                                    ))
                                    seen_edges.add(edge_key)

                # 6. Get File -> Symbol CONTAINS edges
                contains_query = VisualizationQueries.ARCHITECTURE_CONTAINS
                result = session.run(cast(LiteralString, contains_query), repo_id=repo_id)
                for record in result:
                    file_id = record["file_id"]
                    symbol_id = record["symbol_id"]
                    if file_id in nodes and symbol_id in nodes:
                        edge_key = (file_id, symbol_id, GraphEdgeType.CONTAINS.value)
                        if edge_key not in seen_edges:
                            edges.append(VisEdge(
                                source=file_id,
                                target=symbol_id,
                                edge_type=GraphEdgeType.CONTAINS,
                            ))
                            seen_edges.add(edge_key)

                # Use fallback to semantic edges (proper service injection should be used at higher levels)
                relationship_types = GraphEdgeType.semantic_edges()

                max_depth = DEFAULT_TRAVERSAL_DEPTH

                for rel_type in relationship_types:
                    # Use centralized query with variable depth
                    rel_query = VisualizationQueries.build_comprehensive_edges_query(rel_type, max_depth)
                    result = session.run(cast(LiteralString, rel_query), repo_id=repo_id)

                    edge_type = GraphEdgeType(rel_type)
                    for record in result:
                        from_id = record["from_id"]
                        to_id = record["to_id"]
                        if from_id in nodes and to_id in nodes:
                            edge_key = (from_id, to_id, rel_type)
                            if edge_key not in seen_edges:
                                edges.append(VisEdge(
                                    source=from_id,
                                    target=to_id,
                                    edge_type=edge_type,
                                ))
                                seen_edges.add(edge_key)

            # Apply limit - prioritize keeping connected components
            if len(nodes) > limit:
                # Keep repo, directories, and a subset of files/symbols
                repo_nodes = [n for n in nodes.values() if n.node_type == GraphNodeType.REPO]
                dir_nodes = [n for n in nodes.values() if n.node_type == GraphNodeType.DIRECTORY]
                file_nodes = [n for n in nodes.values() if n.node_type == GraphNodeType.FILE]
                symbol_nodes = [n for n in nodes.values() if n.node_type == GraphNodeType.SYMBOL]

                # Calculate how many of each type to keep
                remaining = limit - len(repo_nodes) - len(dir_nodes)
                file_limit = min(len(file_nodes), remaining // 2)
                symbol_limit = remaining - file_limit

                selected_files = file_nodes[:file_limit]
                selected_symbols = symbol_nodes[:symbol_limit]

                node_list = repo_nodes + dir_nodes + selected_files + selected_symbols
                node_ids = {n.id for n in node_list}
            else:
                node_list = list[VisNode](nodes.values())
                node_ids = set[str](nodes.keys())

            # Filter edges to only include those between included nodes
            filtered_edges = [
                e for e in edges if e.source in node_ids and e.target in node_ids
            ]

            return VisGraph(nodes=node_list, edges=filtered_edges)

        except Exception as e:
            logger.error(f"Failed to query comprehensive graph for repo {repo_id}: {e}")
            return VisGraph()
