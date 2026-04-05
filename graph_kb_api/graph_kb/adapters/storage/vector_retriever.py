"""Adapter for neo4j-graphrag VectorCypherRetriever with graph expansion.

This module wraps neo4j-graphrag's VectorCypherRetriever for hybrid search
combining vector similarity with graph traversal.
"""

import hashlib
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models import EmbedderNotConfiguredError
from ...models.base import GraphNode
from ...models.enums import GraphEdgeType, GraphNodeType
from ...models.visualization import VisEdge, VisGraph, VisNode
from ...querying.models import ContextPacket, GraphRAGResult

if TYPE_CHECKING:
    from ...storage.neo4j.edge_repository import EdgeRepository
    from ...storage.neo4j.vector_repository import VectorRepository
    from ..external.embedder_adapter import EmbedderAdapter

logger = EnhancedLogger(__name__)


class VectorCypherRetrieverAdapter:
    """Adapter for neo4j-graphrag VectorCypherRetriever with graph expansion.

    Combines vector similarity search with Cypher graph traversal to find
    semantically similar code symbols and expand their graph neighborhoods.

    This adapter uses the repository layer (VectorRepository, EdgeRepository)
    for all database operations instead of direct Cypher queries.
    """

    def __init__(
        self,
        vector_repository: "VectorRepository",
        edge_repository: "EdgeRepository",
        embedder: "EmbedderAdapter",
        index_name: str = "chunk_embeddings",
        database: str = "neo4j",
        default_expansion_depth: int = 10,
    ):
        """Initialize the adapter with repository layer components.

        Args:
            vector_repository: VectorRepository instance for vector search operations.
            edge_repository: EdgeRepository instance for graph expansion operations.
            embedder: EmbedderAdapter instance for generating query embeddings.
            index_name: Name of the vector index in Neo4j (default: "chunk_embeddings").
            database: Name of the Neo4j database to use (default: "neo4j").
            default_expansion_depth: Default depth for graph expansion (default: 3).

        Raises:
            EmbedderNotConfiguredError: If embedder is None.
        """
        if embedder is None:
            raise EmbedderNotConfiguredError(
                "Embedder is required for VectorCypherRetrieverAdapter"
            )

        self._vector_repo = vector_repository
        self._edge_repo = edge_repository
        self._embedder = embedder
        self._index_name = index_name
        self._database = database
        self._default_expansion_depth = default_expansion_depth

    def search_with_context(
        self,
        query: str,
        repo_id: str,
        top_k: int = 30,
        expansion_depth: Optional[int] = None,
        max_expansion_nodes: int = 500,
        include_visualization: bool = True,
    ) -> GraphRAGResult:
        """Search for symbols and expand their graph neighborhoods.

        Performs vector similarity search to find relevant symbols,
        then expands their graph neighborhoods using the repository layer.

        Args:
            query: Natural language query.
            repo_id: Repository identifier to filter results.
            top_k: Maximum number of initial vector search results.
            expansion_depth: Depth for graph expansion (defaults to default_expansion_depth).
            max_expansion_nodes: Maximum nodes to return per symbol expansion.
            include_visualization: Whether to generate a Mermaid diagram visualization.

        Returns:
            GraphRAGResult containing context packets, visualization, and metadata.
        """
        depth = expansion_depth if expansion_depth is not None else self._default_expansion_depth

        # Generate query embedding using EmbedderAdapter
        query_embedding = self._embedder.embed_query(query)

        # Get available edge types for this repository
        edge_types = self._edge_repo.get_available_edge_types(repo_id)

        # Use VectorRepository's hybrid_search for combined vector + graph search
        vector_results, expanded_nodes = self._vector_repo.hybrid_search(
            query_embedding=query_embedding,
            repo_id=repo_id,
            top_k=top_k,
            expand_graph=True,
            expansion_hops=depth,
            max_expansion_nodes=max_expansion_nodes,
            edge_types=edge_types,
        )

        # Build GraphRAGResult from repository results
        return self._build_graph_rag_result(
            vector_results=vector_results,
            expanded_nodes=expanded_nodes,
            query=query,
            repo_id=repo_id,
            expansion_depth=depth,
            edge_types=edge_types,
            include_visualization=include_visualization,
        )

    def _build_graph_rag_result(
        self,
        vector_results: List[Any],
        expanded_nodes: List[GraphNode],
        query: str,
        repo_id: str,
        expansion_depth: int,
        edge_types: List[str],
        include_visualization: bool = True,
    ) -> GraphRAGResult:
        """Build GraphRAGResult from repository search results.

        Args:
            vector_results: List of VectorSearchResult from VectorRepository.
            expanded_nodes: List of GraphNode from graph expansion.
            query: Original search query.
            repo_id: Repository identifier.
            expansion_depth: Depth used for expansion.
            edge_types: Edge types used for traversal.
            include_visualization: Whether to generate a VisGraph for interactive visualization.

        Returns:
            GraphRAGResult with context packets and optional VisGraph visualization.
        """
        context_packets: List[ContextPacket] = []
        symbols_found: List[str] = []

        # Create a map of expanded nodes by ID for quick lookup
        expanded_map: Dict[str, GraphNode] = {node.id: node for node in expanded_nodes}

        # Track unique nodes explored (vector results + expanded nodes)
        all_explored_ids: Set[str] = set()
        all_nodes: List[GraphNode] = []
        seen_node_ids: Set[str] = set()

        for result in vector_results:
            node_id = result.node_id
            all_explored_ids.add(node_id)
            node = result.node
            content = result.content

            # Add node to all_nodes if not seen
            if node_id not in seen_node_ids:
                all_nodes.append(node)
                seen_node_ids.add(node_id)

            # Extract attrs from the node
            attrs = node.attrs if node.attrs else {}

            # Extract symbol name from attrs or use node_id
            symbol_name = attrs.get("name") or self._extract_symbol_name(attrs, node_id)
            symbols_found.append(symbol_name)

            # Find related nodes from expanded_nodes that are connected to this result
            related_nodes = self._find_related_nodes(node_id, expanded_nodes, expanded_map)

            # Track expanded node IDs and add to all_nodes
            for rn in related_nodes:
                all_explored_ids.add(rn.id)
                if rn.id not in seen_node_ids:
                    all_nodes.append(rn)
                    seen_node_ids.add(rn.id)

            # Build symbols included list
            symbols_included = [symbol_name]
            for related_node in related_nodes:
                related_attrs = related_node.attrs if related_node.attrs else {}
                related_name = related_attrs.get("name") or related_node.id
                if related_name and related_name not in symbols_included:
                    symbols_included.append(related_name)

            # Build content string
            context_content = self._build_context_content(
                symbol_name=symbol_name,
                attrs=attrs,
                summary=node.summary,
                content=content,
                related_nodes=related_nodes,
            )

            # Generate packet ID from content hash
            packet_id = self._generate_packet_id(node_id, context_content)

            # Calculate depth based on related nodes
            max_depth = min(len(related_nodes), expansion_depth) if related_nodes else 0

            context_packets.append(ContextPacket(
                packet_id=packet_id,
                root_symbol=symbol_name,
                content=context_content,
                node_count=1 + len(related_nodes),
                depth=max_depth,
                symbols_included=symbols_included,
                relationships_described=["CALLS", "IMPORTS", "EXTENDS", "CONTAINS"],
            ))

        # Generate VisGraph for interactive visualization if requested
        vis_graph: Optional[VisGraph] = None
        if include_visualization and all_nodes:
            vis_graph = self._generate_vis_graph(all_nodes=all_nodes, repo_id=repo_id, edge_types=edge_types)

        return GraphRAGResult(
            query=query,
            context_packets=context_packets,
            visualization=None,  # Mermaid diagram not used
            symbols_found=symbols_found,
            total_nodes_explored=len(all_explored_ids),
            retrieval_strategy=f"vector_cypher_depth_{expansion_depth}",
            vis_graph=vis_graph,
        )

    def _generate_vis_graph(
        self,
        all_nodes: List[GraphNode],
        repo_id: str,
        edge_types: List[str],
    ) -> Optional[VisGraph]:
        """Generate a VisGraph for interactive pyvis visualization.

        Extracts symbol names from Chunk nodes, resolves them to Symbol nodes,
        and then gets their relationships for visualization.

        Args:
            all_nodes: List of all nodes discovered during traversal (may be Chunks).

        Returns:
            VisGraph with nodes and edges for pyvis rendering, or None if generation fails.
        """
        if not all_nodes:
            return None

        try:
            vis_nodes: List[VisNode] = []
            vis_edges: List[VisEdge] = []
            seen_node_ids: Set[str] = set()
            seen_edge_keys: Set[tuple] = set()

            # Collect symbol names from chunk nodes to resolve to Symbol nodes
            symbol_names_to_resolve: Set[str] = set()

            for node in all_nodes:
                attrs = node.attrs or {}

                # If this is a Symbol node, add it directly
                if node.type == GraphNodeType.SYMBOL:
                    if node.id not in seen_node_ids:
                        vis_nodes.append(VisNode.from_graph_node(node))
                        seen_node_ids.add(node.id)
                    continue

                # For Chunk nodes, extract symbols_defined to resolve later
                symbols_defined = attrs.get("symbols_defined", [])
                if isinstance(symbols_defined, str):
                    symbols_defined = [s.strip() for s in symbols_defined.split(",") if s.strip()]
                if symbols_defined:
                    symbol_names_to_resolve.update(symbols_defined[:3])  # Limit per chunk

            # If we only have chunks, we need to get Symbol nodes and their relationships
            # Use EdgeRepository to find Symbol nodes by traversing from chunks
            if symbol_names_to_resolve and not vis_nodes:
                logger.debug(f"Resolving {len(symbol_names_to_resolve)} symbol names for visualization")

                # For each symbol name, try to find and traverse from it
                for symbol_name in list(symbol_names_to_resolve)[:20]:  # Limit to 20 symbols
                    try:
                        # Get reachable nodes from this symbol using EdgeRepository
                        # First we need to find the symbol node ID
                        reachable_nodes, edges = self._edge_repo.get_reachable_nodes(
                            start_id=symbol_name,  # This might not work directly
                            edge_types=edge_types,
                            max_depth=2,
                            direction="both",
                        )

                        # Add discovered nodes
                        for rnode in reachable_nodes:
                            if rnode.id not in seen_node_ids:
                                vis_nodes.append(VisNode.from_graph_node(rnode))
                                seen_node_ids.add(rnode.id)

                        # Add discovered edges
                        for edge_dict in edges:
                            source = edge_dict.get("source", "")
                            target = edge_dict.get("target", "")
                            edge_type_str = edge_dict.get("type", "CALLS")

                            edge_key = (source, target)
                            if edge_key not in seen_edge_keys and source in seen_node_ids and target in seen_node_ids:
                                try:
                                    edge_type = GraphEdgeType(edge_type_str)
                                except ValueError:
                                    edge_type = GraphEdgeType.CALLS

                                vis_edges.append(VisEdge(
                                    source=source,
                                    target=target,
                                    edge_type=edge_type,
                                ))
                                seen_edge_keys.add(edge_key)

                    except Exception as e:
                        logger.debug(f"Failed to get reachable nodes for symbol {symbol_name}: {e}")
                        continue

            # If we have Symbol nodes, get their relationships
            if vis_nodes:
                node_ids = {n.id for n in vis_nodes}

                for vis_node in vis_nodes[:60]:  # Limit for performance
                    try:
                        neighbors = self._edge_repo.get_neighbors(
                            node_id=vis_node.id,
                            edge_types=edge_types,
                            direction="both",
                            limit=20,
                        )

                        for neighbor in neighbors:
                            # Add neighbor if not seen
                            if neighbor.id not in seen_node_ids:
                                vis_nodes.append(VisNode.from_graph_node(neighbor))
                                seen_node_ids.add(neighbor.id)
                                node_ids.add(neighbor.id)

                            # Add edge if both nodes are in our set
                            if neighbor.id in node_ids:
                                edge_key_out = (vis_node.id, neighbor.id)
                                edge_key_in = (neighbor.id, vis_node.id)

                                if edge_key_out not in seen_edge_keys and edge_key_in not in seen_edge_keys:
                                    vis_edges.append(VisEdge(
                                        source=vis_node.id,
                                        target=neighbor.id,
                                        edge_type=GraphEdgeType.CALLS,
                                    ))
                                    seen_edge_keys.add(edge_key_out)

                    except Exception as e:
                        logger.debug(f"Failed to get neighbors for {vis_node.id}: {e}")
                        continue

            # If still no nodes, fall back to showing chunks as-is
            if not vis_nodes:
                for node in all_nodes[:50]:
                    if node.id not in seen_node_ids:
                        vis_nodes.append(VisNode.from_graph_node(node))
                        seen_node_ids.add(node.id)

            logger.debug(f"Generated VisGraph with {len(vis_nodes)} nodes and {len(vis_edges)} edges")
            return VisGraph(nodes=vis_nodes, edges=vis_edges)

        except Exception as e:
            logger.warning(f"Failed to generate VisGraph: {e}")
            return None

    def _extract_symbol_name(self, attrs: Dict[str, Any], fallback: str) -> str:
        """Extract symbol name from attributes.

        Args:
            attrs: Node attributes dictionary.
            fallback: Fallback value if name not found.

        Returns:
            Symbol name string.
        """
        # Try common attribute names for symbol identification
        for key in ["name", "symbol_name", "function_name", "class_name"]:
            if key in attrs and attrs[key]:
                return str(attrs[key])

        # Try to extract from symbols_defined
        symbols_defined = attrs.get("symbols_defined", [])
        if symbols_defined:
            if isinstance(symbols_defined, list) and symbols_defined:
                return str(symbols_defined[0])
            elif isinstance(symbols_defined, str) and symbols_defined:
                return symbols_defined.split(",")[0].strip()

        return fallback

    def _find_related_nodes(
        self,
        node_id: str,
        expanded_nodes: List[GraphNode],
        expanded_map: Dict[str, GraphNode],
    ) -> List[GraphNode]:
        """Find nodes related to a given node from the expanded set.

        Args:
            node_id: ID of the source node.
            expanded_nodes: List of all expanded nodes.
            expanded_map: Map of node ID to GraphNode for quick lookup.

        Returns:
            List of related GraphNode objects.
        """
        # For now, return all expanded nodes as potentially related
        # In a more sophisticated implementation, we could use EdgeRepository
        # to find actual relationships
        return [node for node in expanded_nodes if node.id != node_id]

    def _build_context_content(
        self,
        symbol_name: str,
        attrs: Dict[str, Any],
        summary: Optional[str],
        content: Optional[str],
        related_nodes: List[GraphNode],
    ) -> str:
        """Build the text content for a context packet.

        Args:
            symbol_name: Name of the root symbol.
            attrs: Symbol attributes.
            summary: Optional summary text.
            content: Optional content text (e.g., code chunk).
            related_nodes: Related nodes from graph expansion.

        Returns:
            Formatted content string.
        """
        lines = []

        # Root symbol info
        lines.append(f"Symbol: {symbol_name}")

        kind = attrs.get("kind", "unknown")
        lines.append(f"Type: {kind}")

        file_path = attrs.get("file_path", "")
        if file_path:
            lines.append(f"File: {file_path}")

        # Line range if available
        start_line = attrs.get("start_line")
        end_line = attrs.get("end_line")
        if start_line is not None and end_line is not None:
            lines.append(f"Lines: {start_line}-{end_line}")

        docstring = attrs.get("docstring", "")
        if docstring:
            lines.append(f"Description: {docstring}")

        if summary:
            lines.append(f"Summary: {summary}")

        # Include content snippet if available
        if content:
            lines.append("")
            lines.append("Content:")
            # Truncate content if too long
            content_preview = content[:500] + "..." if len(content) > 500 else content
            lines.append(content_preview)

        # Related symbols
        if related_nodes:
            lines.append("")
            lines.append("Related symbols:")
            for related_node in related_nodes:
                related_attrs = related_node.attrs if related_node.attrs else {}
                related_name = related_attrs.get("name") or related_node.id
                related_kind = related_attrs.get("kind", "unknown")
                lines.append(f"  - {related_name} ({related_kind})")

        return "\n".join(lines)

    def _generate_packet_id(self, node_id: str, content: str) -> str:
        """Generate a deterministic packet ID from content.

        Args:
            node_id: ID of the root node.
            content: Content string.

        Returns:
            Deterministic packet ID (16 character hex string).
        """
        hash_input = f"{node_id}:{content}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]
