"""Neo4j GraphRAG native retrievers using neo4j-graphrag library.

This module provides adapters that use neo4j-graphrag's built-in retrievers:
- VectorCypherRetriever: Vector similarity + Cypher graph traversal
- HybridCypherRetriever: Vector + full-text search + graph traversal

These retrievers handle traversal logic internally, eliminating the need
for custom iterative deepening implementations.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from neo4j import Driver, GraphDatabase

try:
    from neo4j_graphrag.embeddings import Embeddings
    from neo4j_graphrag.retrievers import HybridCypherRetriever, VectorCypherRetriever
    NEO4J_GRAPHRAG_AVAILABLE = True
except ImportError:
    # neo4j_graphrag is optional dependency
    VectorCypherRetriever = None
    HybridCypherRetriever = None
    Embeddings = None
    NEO4J_GRAPHRAG_AVAILABLE = False

from ...models import EmbedderNotConfiguredError
from ...models.enums import RelationshipType
from ...querying.models import ContextPacket, GraphRAGResult
from ...storage.neo4j.queries import TraversalQueries

if TYPE_CHECKING:
    from ..external.embedder_adapter import EmbedderAdapter


if NEO4J_GRAPHRAG_AVAILABLE:
    class Neo4jGraphRAGEmbedderWrapper(Embeddings):
        """Wrapper to make EmbedderAdapter compatible with neo4j-graphrag Embeddings interface."""

        def __init__(self, embedder: "EmbedderAdapter"):
            self._embedder = embedder

        def embed_query(self, text: str) -> List[float]:
            return self._embedder.embed_query(text)

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            return self._embedder.embed_batch(texts)
else:
    class Neo4jGraphRAGEmbedderWrapper:
        """Dummy wrapper when neo4j-graphrag is not available."""

        def __init__(self, embedder: "EmbedderAdapter"):
            self._embedder = embedder

        def embed_query(self, text: str) -> List[float]:
            raise ImportError("neo4j-graphrag is not available")

        def embed_documents(self, texts: List[str]) -> List[List[float]]:
            raise ImportError("neo4j-graphrag is not available")


class BaseGraphRAGRetriever(ABC):
    """Base class for neo4j-graphrag retriever adapters.

    Provides shared functionality for building GraphRAGResult objects
    and formatting context content from retriever results.
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        embedder: "EmbedderAdapter",
        database: str = "neo4j",
    ):
        """Initialize base retriever components.

        Args:
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
            embedder: EmbedderAdapter for generating query embeddings.
            database: Neo4j database name.
        """
        if embedder is None:
            raise EmbedderNotConfiguredError(
                f"Embedder is required for {self.__class__.__name__}"
            )

        self._driver: Driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password)
        )
        self._embedder = embedder
        self._embedder_wrapper = Neo4jGraphRAGEmbedderWrapper(embedder)
        self._database = database
        self._retriever: Union[VectorCypherRetriever, HybridCypherRetriever, None] = None

    @abstractmethod
    def search_with_context(
        self,
        query: str,
        repo_id: str,
        top_k: int = 10,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> GraphRAGResult:
        """Search and retrieve graph context. Implemented by subclasses."""
        pass

    @property
    @abstractmethod
    def retrieval_strategy(self) -> str:
        """Return the retrieval strategy name for this retriever."""
        pass

    @property
    @abstractmethod
    def packet_id_prefix(self) -> str:
        """Return the prefix for context packet IDs."""
        pass

    def _execute_search(
        self,
        query: str,
        repo_id: str,
        top_k: int,
        filter_params: Optional[Dict[str, Any]],
    ) -> Any:
        """Execute search using the configured retriever."""
        query_params = {"repo_id": repo_id}
        if filter_params:
            query_params.update(filter_params)

        return self._retriever.search(
            query_text=query,
            top_k=top_k,
            query_params=query_params,
        )

    def _build_graph_rag_result(
        self,
        retriever_results: Any,
        query: str,
    ) -> GraphRAGResult:
        """Build GraphRAGResult from retriever results.

        Args:
            retriever_results: Results from neo4j-graphrag retriever.
            query: Original search query.

        Returns:
            GraphRAGResult with context packets.
        """
        context_packets: List[ContextPacket] = []
        symbols_found: List[str] = []
        total_nodes_explored = 0

        for i, item in enumerate(retriever_results.items):
            content = item.content
            metadata = item.metadata or {}

            # Extract common node information
            node_id = metadata.get("node_id", f"node_{i}")
            name = metadata.get("name", node_id)
            kind = metadata.get("kind", "unknown")
            file_path = metadata.get("file_path", "")
            summary = metadata.get("summary", "")
            docstring = metadata.get("docstring", "")
            start_line = metadata.get("start_line")
            end_line = metadata.get("end_line")

            # Get related nodes - normalize different formats to unified structure
            related_nodes = self._extract_related_nodes(metadata)

            symbols_found.append(name)

            # Build symbols included list
            symbols_included = [name]
            for node in related_nodes[:15]:
                if node.get("name") and node["name"] not in symbols_included:
                    symbols_included.append(node["name"])

            # Extract relationship types
            rel_types = self._extract_relationship_types(related_nodes)

            # Build context content
            context_content = self._build_context_content(
                name=name,
                kind=kind,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                content=content,
                summary=summary,
                docstring=docstring,
                related_nodes=related_nodes,
            )

            node_count = 1 + len(related_nodes)
            total_nodes_explored += node_count

            # Determine max depth from related nodes
            max_depth = max(
                (n.get("distance", 0) for n in related_nodes),
                default=0
            )

            context_packets.append(ContextPacket(
                packet_id=f"{self.packet_id_prefix}_{node_id}_{i}",
                root_symbol=name,
                content=context_content,
                node_count=node_count,
                depth=max_depth,
                symbols_included=symbols_included,
                relationships_described=rel_types,
            ))

        return GraphRAGResult(
            context_packets=context_packets,
            visualization=None,
            symbols_found=symbols_found,
            total_nodes_explored=total_nodes_explored,
            retrieval_strategy=self.retrieval_strategy,
        )

    def _extract_related_nodes(self, metadata: Dict[str, Any]) -> List[Dict]:
        """Extract and normalize related nodes from metadata.

        Handles different formats:
        - hop1_neighbors/hop2_neighbors (VectorCypherRetriever)
        - related_nodes with distance (HybridCypherRetriever)
        - traversed_nodes with path_rels (HybridGraphTraversalRetriever)

        Returns unified format: [{id, name, kind, type, distance, rel_type}, ...]
        """
        # Check for traversed_nodes format (most detailed)
        if "traversed_nodes" in metadata:
            nodes = metadata["traversed_nodes"]
            return [
                {
                    "id": n.get("id"),
                    "name": n.get("name"),
                    "kind": n.get("kind"),
                    "type": n.get("type"),
                    "file_path": n.get("file_path"),
                    "distance": n.get("distance", 1),
                    "rel_type": n.get("path_rels", ["RELATED"])[-1] if n.get("path_rels") else "RELATED",
                    "path_rels": n.get("path_rels", []),
                }
                for n in nodes
            ]

        # Check for related_nodes format (with distance)
        if "related_nodes" in metadata:
            nodes = metadata["related_nodes"]
            return [
                {
                    "id": n.get("id"),
                    "name": n.get("name"),
                    "kind": n.get("kind"),
                    "type": n.get("type"),
                    "distance": n.get("distance", 1),
                    "rel_type": "RELATED",
                }
                for n in nodes
            ]

        # Check for hop1/hop2 format
        result = []
        for neighbor in metadata.get("hop1_neighbors", []):
            result.append({
                "id": neighbor.get("id"),
                "name": neighbor.get("name"),
                "kind": neighbor.get("kind"),
                "type": neighbor.get("type"),
                "distance": 1,
                "rel_type": neighbor.get("rel_type", "RELATED"),
            })
        for neighbor in metadata.get("hop2_neighbors", []):
            result.append({
                "id": neighbor.get("id"),
                "name": neighbor.get("name"),
                "kind": neighbor.get("kind"),
                "type": neighbor.get("type"),
                "distance": 2,
                "rel_type": neighbor.get("rel_type", "RELATED"),
            })

        return result

    def _extract_relationship_types(self, related_nodes: List[Dict]) -> List[str]:
        """Extract unique relationship types from related nodes."""
        rel_types = set()
        for n in related_nodes:
            if n.get("rel_type"):
                rel_types.add(n["rel_type"])
            for rel in n.get("path_rels", []):
                rel_types.add(rel)
        return list(rel_types) if rel_types else ["RELATED"]

    def _build_context_content(
        self,
        name: str,
        kind: str,
        file_path: str,
        start_line: Optional[int],
        end_line: Optional[int],
        content: str,
        summary: str,
        docstring: str,
        related_nodes: List[Dict],
    ) -> str:
        """Build formatted context content string.

        Args:
            name: Symbol name.
            kind: Symbol kind/type.
            file_path: File path.
            start_line: Start line number.
            end_line: End line number.
            content: Code content.
            summary: Summary text.
            docstring: Docstring text.
            related_nodes: List of related nodes with distance info.

        Returns:
            Formatted context string.
        """
        lines = [f"Symbol: {name}", f"Type: {kind}"]

        if file_path:
            lines.append(f"File: {file_path}")
        if start_line is not None and end_line is not None:
            lines.append(f"Lines: {start_line}-{end_line}")
        if docstring:
            lines.append(f"Description: {docstring}")
        if summary:
            lines.append(f"Summary: {summary}")

        if content:
            lines.append("")
            lines.append("Content:")
            content_preview = content[:500] + "..." if len(content) > 500 else content
            lines.append(content_preview)

        if related_nodes:
            # Group by distance for hierarchical display
            by_distance: Dict[int, List[Dict]] = {}
            for n in related_nodes:
                dist = n.get("distance", 1)
                by_distance.setdefault(dist, []).append(n)

            for dist in sorted(by_distance.keys()):
                lines.append("")
                hop_label = "hop" if dist == 1 else "hops"
                lines.append(f"Related symbols ({dist} {hop_label} away):")

                # Group by relationship type within distance
                by_rel: Dict[str, List[Dict]] = {}
                for n in by_distance[dist]:
                    rel_key = n.get("rel_type", "RELATED")
                    by_rel.setdefault(rel_key, []).append(n)

                for rel_type, nodes in by_rel.items():
                    for n in nodes[:5]:  # Limit per relationship type
                        n_file = n.get("file_path", "")
                        file_info = f" in {n_file}" if n_file else ""
                        lines.append(
                            f"  - [{rel_type}] {n.get('name', 'unknown')} "
                            f"({n.get('kind', 'unknown')}){file_info}"
                        )

        return "\n".join(lines)

    def close(self):
        """Close the Neo4j driver connection."""
        if self._driver:
            self._driver.close()


class VectorCypherRetrieverAdapter(BaseGraphRAGRetriever):
    """Adapter using neo4j-graphrag's VectorCypherRetriever.

    Combines vector similarity search with Cypher queries to traverse
    the graph from semantically similar nodes.
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        embedder: "EmbedderAdapter",
        index_name: str = "chunk_embeddings",
        database: str = "neo4j",
        retrieval_query: Optional[str] = None,
    ):
        """Initialize the VectorCypherRetriever adapter.

        Args:
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
            embedder: EmbedderAdapter for generating query embeddings.
            index_name: Name of the vector index in Neo4j.
            database: Neo4j database name.
            retrieval_query: Custom Cypher query for graph expansion.
                           If None, uses TraversalQueries.VECTOR_CYPHER_RETRIEVAL.
        """
        super().__init__(neo4j_uri, neo4j_user, neo4j_password, embedder, database)

        self._index_name = index_name
        self._retrieval_query = retrieval_query or TraversalQueries.VECTOR_CYPHER_RETRIEVAL

        self._retriever = VectorCypherRetriever(
            driver=self._driver,
            index_name=self._index_name,
            retrieval_query=self._retrieval_query,
            embedder=self._embedder_wrapper,
            neo4j_database=self._database,
        )

    @property
    def retrieval_strategy(self) -> str:
        return "neo4j_graphrag_vector_cypher"

    @property
    def packet_id_prefix(self) -> str:
        return "vc"

    def search_with_context(
        self,
        query: str,
        repo_id: str,
        top_k: int = 10,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> GraphRAGResult:
        """Search for symbols and retrieve graph context."""
        results = self._execute_search(query, repo_id, top_k, filter_params)
        return self._build_graph_rag_result(results, query)


class HybridCypherRetrieverAdapter(BaseGraphRAGRetriever):
    """Adapter using neo4j-graphrag's HybridCypherRetriever.

    Combines vector search + full-text search + graph traversal.
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        embedder: "EmbedderAdapter",
        vector_index_name: str = "chunk_embeddings",
        fulltext_index_name: str = "chunk_fulltext",
        database: str = "neo4j",
        retrieval_query: Optional[str] = None,
    ):
        """Initialize the HybridCypherRetriever adapter.

        Args:
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
            embedder: EmbedderAdapter for generating query embeddings.
            vector_index_name: Name of the vector index in Neo4j.
            fulltext_index_name: Name of the full-text index in Neo4j.
            database: Neo4j database name.
            retrieval_query: Custom Cypher query for graph expansion.
                           If None, uses TraversalQueries.HYBRID_CYPHER_RETRIEVAL.
        """
        super().__init__(neo4j_uri, neo4j_user, neo4j_password, embedder, database)

        self._vector_index_name = vector_index_name
        self._fulltext_index_name = fulltext_index_name
        self._retrieval_query = retrieval_query or TraversalQueries.HYBRID_CYPHER_RETRIEVAL

        self._retriever = HybridCypherRetriever(
            driver=self._driver,
            vector_index_name=self._vector_index_name,
            fulltext_index_name=self._fulltext_index_name,
            retrieval_query=self._retrieval_query,
            embedder=self._embedder_wrapper,
            neo4j_database=self._database,
        )

    @property
    def retrieval_strategy(self) -> str:
        return "neo4j_graphrag_hybrid_cypher"

    @property
    def packet_id_prefix(self) -> str:
        return "hc"

    def search_with_context(
        self,
        query: str,
        repo_id: str,
        top_k: int = 10,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> GraphRAGResult:
        """Search using hybrid (vector + full-text) with graph traversal."""
        results = self._execute_search(query, repo_id, top_k, filter_params)
        return self._build_graph_rag_result(results, query)


class HybridGraphTraversalRetriever(BaseGraphRAGRetriever):
    """Combined retriever for hybrid search with configurable graph traversal.

    Provides a unified interface that can use either VectorCypherRetriever
    or HybridCypherRetriever based on configuration, with customizable
    traversal depth and relationship filtering.
    """

    DEFAULT_RELATIONSHIP_TYPES = [r.value for r in RelationshipType]

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        embedder: "EmbedderAdapter",
        vector_index_name: str = "chunk_embeddings",
        fulltext_index_name: Optional[str] = None,
        database: str = "neo4j",
        default_traversal_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
    ):
        """Initialize the hybrid graph traversal retriever.

        Args:
            neo4j_uri: Neo4j connection URI.
            neo4j_user: Neo4j username.
            neo4j_password: Neo4j password.
            embedder: EmbedderAdapter for generating query embeddings.
            vector_index_name: Name of the vector index.
            fulltext_index_name: Name of full-text index. If provided, enables
                               hybrid mode (vector + full-text search).
            database: Neo4j database name.
            default_traversal_depth: Default depth for graph traversal (1-3).
            relationship_types: List of relationship types to traverse.
                              If None, uses DEFAULT_RELATIONSHIP_TYPES.
        """
        super().__init__(neo4j_uri, neo4j_user, neo4j_password, embedder, database)

        self._vector_index_name = vector_index_name
        self._fulltext_index_name = fulltext_index_name
        self._default_traversal_depth = min(max(default_traversal_depth, 1), 3)
        self._relationship_types = relationship_types or self.DEFAULT_RELATIONSHIP_TYPES

        # Build retrieval query and initialize retriever
        self._retrieval_query = self._build_traversal_query(self._default_traversal_depth)
        self._mode = "hybrid" if fulltext_index_name else "vector"
        self._retriever = self._create_retriever(self._retrieval_query)

    def _create_retriever(
        self,
        retrieval_query: str,
    ) -> Union[VectorCypherRetriever, HybridCypherRetriever]:
        """Create the appropriate retriever based on mode."""
        if self._mode == "hybrid":
            return HybridCypherRetriever(
                driver=self._driver,
                vector_index_name=self._vector_index_name,
                fulltext_index_name=self._fulltext_index_name,
                retrieval_query=retrieval_query,
                embedder=self._embedder_wrapper,
                neo4j_database=self._database,
            )
        return VectorCypherRetriever(
            driver=self._driver,
            index_name=self._vector_index_name,
            retrieval_query=retrieval_query,
            embedder=self._embedder_wrapper,
            neo4j_database=self._database,
        )

    def _build_traversal_query(self, depth: int) -> str:
        """Build Cypher query for graph traversal with specified depth."""
        return TraversalQueries.build_traversal_query(depth, self._relationship_types)

    @property
    def retrieval_strategy(self) -> str:
        return f"neo4j_graphrag_{self._mode}_traversal_depth_{self._default_traversal_depth}"

    @property
    def packet_id_prefix(self) -> str:
        return "hgt"

    @property
    def mode(self) -> str:
        """Get the current retrieval mode ('vector' or 'hybrid')."""
        return self._mode

    @property
    def traversal_depth(self) -> int:
        """Get the default traversal depth."""
        return self._default_traversal_depth

    @property
    def relationship_types(self) -> List[str]:
        """Get the configured relationship types for traversal."""
        return self._relationship_types.copy()

    def search_with_context(
        self,
        query: str,
        repo_id: str,
        top_k: int = 10,
        traversal_depth: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> GraphRAGResult:
        """Search with configurable graph traversal.

        Args:
            query: Natural language query.
            repo_id: Repository identifier.
            top_k: Maximum number of results.
            traversal_depth: Override default traversal depth (1-3).
            filter_params: Additional filter parameters.

        Returns:
            GraphRAGResult with context packets from traversal.
        """
        # Use custom depth if specified and different from default
        if traversal_depth and traversal_depth != self._default_traversal_depth:
            depth = min(max(traversal_depth, 1), 3)
            custom_query = self._build_traversal_query(depth)
            retriever = self._create_retriever(custom_query)
        else:
            retriever = self._retriever

        query_params = {"repo_id": repo_id}
        if filter_params:
            query_params.update(filter_params)

        results = retriever.search(
            query_text=query,
            top_k=top_k,
            query_params=query_params,
        )

        return self._build_graph_rag_result(results, query)
