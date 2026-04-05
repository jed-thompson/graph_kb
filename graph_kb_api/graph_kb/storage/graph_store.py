"""Neo4j Graph Store implementation with Vector Index support.

This module provides graph storage with integrated vector search capabilities
using Neo4j's native vector index feature (5.11+).

The Neo4jGraphStore class acts as a facade that composes specialized repositories:
- NodeRepository: Node CRUD operations
- EdgeRepository: Edge/relationship operations
- VectorRepository: Vector search operations
- BatchRepository: Bulk/batch operations
"""

import json
import warnings
from typing import Any, Dict, List, Optional, Tuple

from neo4j.exceptions import Neo4jError

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..config import Neo4jConfig
from ..models.base import Chunk, GraphEdge, GraphNode
from ..models.enums import GraphEdgeType

# Import from interfaces
# Import from neo4j package
from .neo4j import (
    BatchRepository,
    EdgeRepository,
    IndexQueries,
    NodeRepository,
    SessionManager,
    StatsQueries,
    VectorRepository,
)
from .neo4j.vector_repository import (
    VectorIndexNotAvailableError,
    VectorSearchResult,
)

logger = EnhancedLogger(__name__)


# Re-export for backward compatibility
__all__ = [
    "Neo4jGraphStore",
    "VectorSearchResult",
    "VectorIndexNotAvailableError",
    "ArchitectureOverview",
]


class ArchitectureOverview:
    """High-level architecture overview of a repository."""

    def __init__(
        self,
        repo_id: str,
        modules: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ):
        self.repo_id = repo_id
        self.modules = modules
        self.relationships = relationships


class Neo4jGraphStore:
    """Graph store facade with integrated vector search using Neo4j Vector Index.

    This class acts as a facade that composes specialized repositories for
    different operation types. It maintains backward compatibility with the
    original monolithic implementation while delegating to:

    - NodeRepository: Node CRUD operations
    - EdgeRepository: Edge/relationship operations
    - VectorRepository: Vector search operations
    - BatchRepository: Bulk/batch operations

    The facade implements the IGraphStore protocol for easy mocking and
    potential backend swapping.
    """

    # Vector index configuration (for backward compatibility)
    VECTOR_INDEX_NAME = "chunk_embeddings"

    def __init__(self, config: Neo4jConfig, vector_dimensions: int = None):
        """Initialize the Neo4j graph store with vector support.

        Args:
            config: Neo4j connection configuration.
            vector_dimensions: Embedding vector dimensions. If None, reads from settings.
        """
        self._config = config

        # Get vector dimensions from settings if not provided
        if vector_dimensions is None:
            from graph_kb_api.config import settings
            vector_dimensions = settings.embedding_dimensions
        self._vector_dimensions = vector_dimensions
        self._indexes_created = False

        # Initialize SessionManager
        self._session_manager = SessionManager(config)

        # Initialize repositories
        self._node_repository = NodeRepository(self._session_manager)
        self._edge_repository = EdgeRepository(self._session_manager)
        self._vector_repository = VectorRepository(
            self._session_manager,
            vector_dimensions=vector_dimensions
        )
        self._batch_repository = BatchRepository(self._session_manager)

    # =========================================================================
    # Repository Properties
    # =========================================================================

    @property
    def session_manager(self) -> SessionManager:
        """Get the SessionManager for direct access.

        .. deprecated:: 2.0
            Direct SessionManager access is deprecated. Use facade methods instead.
        """
        warnings.warn(
            "Direct SessionManager access is deprecated. Use facade methods instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._session_manager

    @property
    def node_repository(self) -> NodeRepository:
        """Get the NodeRepository for direct access."""
        return self._node_repository

    @property
    def edge_repository(self) -> EdgeRepository:
        """Get the EdgeRepository for direct access."""
        return self._edge_repository

    @property
    def vector_repository(self) -> VectorRepository:
        """Get the VectorRepository for direct access."""
        return self._vector_repository

    @property
    def batch_repository(self) -> BatchRepository:
        """Get the BatchRepository for direct access."""
        return self._batch_repository

    # =========================================================================
    # Legacy driver property (for backward compatibility)
    # =========================================================================

    @property
    def driver(self):
        """Get or create the Neo4j driver with connection pooling.

        .. deprecated:: 2.0
            Direct driver access is deprecated. Use facade methods instead.

        This property is maintained for backward compatibility.
        New code should use session_manager instead.
        """
        warnings.warn(
            "Direct driver access is deprecated. Use facade methods instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._session_manager.driver

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        self._session_manager.close()

    def health_check(self) -> bool:
        """Check if the Neo4j connection is healthy."""
        return self._session_manager.health_check()

    # =========================================================================
    # Index Management
    # =========================================================================

    def ensure_indexes(self) -> None:
        """Create indexes including vector index for semantic search."""
        if self._indexes_created:
            return

        with self._session_manager.session() as session:
            # Create uniqueness constraints first (they also create indexes)
            for constraint_query in IndexQueries.get_uniqueness_constraints():
                try:
                    session.run(constraint_query)
                    logger.debug(f"Created constraint: {constraint_query}")
                except Neo4jError as e:
                    # Constraint might already exist - handle gracefully
                    if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                        logger.debug(f"Constraint already exists: {e}")
                    else:
                        logger.warning(f"Constraint creation warning: {e}")

            # Create standard indexes
            for index_query in IndexQueries.get_standard_indexes():
                try:
                    session.run(index_query)
                except Neo4jError as e:
                    logger.warning(f"Index creation warning: {e}")

            # Create vector index for chunk embeddings
            self._vector_repository.ensure_index()

        self._indexes_created = True

    def ensure_chunk_vector_index(
        self,
        index_name: str = None,
        dimensions: int = None,
        similarity: str = None,
    ) -> None:
        """Create vector index for chunk embeddings if it doesn't exist.

        This method is safe to call multiple times - it uses IF NOT EXISTS
        to handle cases where the index already exists.

        Args:
            index_name: Name of the vector index (default: VECTOR_INDEX_NAME).
            dimensions: Embedding dimensions (default: configured vector_dimensions).
            similarity: Similarity function - 'cosine' or 'euclidean' (default: 'cosine').
        """
        self._vector_repository.ensure_index(
            index_name=index_name,
            dimensions=dimensions,
            similarity=similarity or "cosine",
        )

    # =========================================================================
    # Node Operations (delegated to NodeRepository)
    # =========================================================================

    def create_node(self, node: GraphNode) -> None:
        """Create a node in Neo4j with label based on node type.

        Args:
            node: The GraphNode to create.
        """
        self._node_repository.create(node)

    def create_chunk_node(self, chunk: Chunk, embedding: List[float]) -> str:
        """Create a Chunk node with embedding for vector search.

        Args:
            chunk: The Chunk data.
            embedding: Vector embedding for the chunk.

        Returns:
            The chunk node ID.
        """
        return self._node_repository.create_chunk(chunk, embedding)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID from Neo4j.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            The GraphNode if found, None otherwise.
        """
        return self._node_repository.get_by_id(node_id)

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists in the graph."""
        return self._node_repository.exists(node_id)

    def delete_node(self, node_id: str) -> None:
        """Delete a node and its relationships from Neo4j."""
        self._node_repository.delete(node_id)

    def get_chunks_for_file(self, repo_id: str, file_path: str) -> List[GraphNode]:
        """Get all chunk nodes for a specific file."""
        return self._node_repository.get_chunks_for_file(repo_id, file_path)

    def get_chunks_for_symbol(self, repo_id: str, symbol_name: str) -> List[GraphNode]:
        """Get chunks that define or reference a symbol."""
        return self._node_repository.get_chunks_for_symbol(repo_id, symbol_name)

    def get_chunk_with_context(
        self,
        chunk_id: str,
        include_neighbors: bool = True,
    ) -> Tuple[Optional[GraphNode], List[GraphNode]]:
        """Get a chunk node with its graph context.

        Args:
            chunk_id: Chunk node ID.
            include_neighbors: Whether to include neighboring chunks/symbols.

        Returns:
            Tuple of (chunk_node, context_nodes).
        """
        return self._node_repository.get_chunk_with_context(chunk_id, include_neighbors)

    # =========================================================================
    # Edge Operations (delegated to EdgeRepository)
    # =========================================================================

    def create_edge(self, edge: GraphEdge) -> None:
        """Create a relationship between nodes in Neo4j.

        Args:
            edge: The GraphEdge to create.
        """
        self._edge_repository.create(edge)

    def edge_exists(self, from_id: str, to_id: str, edge_type: str) -> bool:
        """Check if an edge exists between two nodes.

        Args:
            from_id: Source node ID.
            to_id: Target node ID.
            edge_type: The type of edge.

        Returns:
            True if the edge exists, False otherwise.
        """
        # Convert string to enum if needed
        if isinstance(edge_type, str):
            edge_type_enum = GraphEdgeType(edge_type)
        else:
            edge_type_enum = edge_type
        return self._edge_repository.exists(from_id, to_id, edge_type_enum)

    def link_symbol_to_chunk(
        self,
        symbol_node_id: str,
        chunk_node_id: str,
    ) -> None:
        """Create REPRESENTED_BY edge from Symbol to Chunk.

        Args:
            symbol_node_id: Symbol node ID.
            chunk_node_id: Chunk node ID.
        """
        edge = GraphEdge(
            id=f"{symbol_node_id}->REPRESENTED_BY->{chunk_node_id}",
            from_node=symbol_node_id,
            to_node=chunk_node_id,
            edge_type=GraphEdgeType.REPRESENTED_BY,
            attrs={},
        )
        self._edge_repository.create(edge)

    def link_file_to_chunk(
        self,
        file_node_id: str,
        chunk_node_id: str,
    ) -> None:
        """Create CONTAINS edge from File to Chunk.

        Args:
            file_node_id: File node ID.
            chunk_node_id: Chunk node ID.
        """
        edge = GraphEdge(
            id=f"{file_node_id}->CONTAINS->{chunk_node_id}",
            from_node=file_node_id,
            to_node=chunk_node_id,
            edge_type=GraphEdgeType.CONTAINS,
            attrs={},
        )
        self._edge_repository.create(edge)

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
        """
        return self._edge_repository.get_neighbors(node_id, edge_types, direction, limit)

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
            Tuple of (nodes, edges).
        """
        return self._edge_repository.get_reachable_nodes(
            start_id, edge_types, max_depth, direction
        )

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
            max_hops: Maximum path length.

        Returns:
            List of node IDs in the path, or None if no path exists.
        """
        return self._edge_repository.find_path(from_id, to_id, edge_types, max_hops)

    # =========================================================================
    # Vector Operations (delegated to VectorRepository)
    # =========================================================================

    def vector_search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> List[VectorSearchResult]:
        """Search for similar chunks using Neo4j vector index.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of VectorSearchResult ordered by similarity.

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
        """
        return self._vector_repository.search(
            query_embedding, repo_id, top_k, min_score
        )

    def hybrid_search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 10,
        expand_graph: bool = True,
        expansion_hops: int = 1,
        max_expand: Optional[int] = None,
    ) -> Tuple[List[VectorSearchResult], List[GraphNode]]:
        """Perform hybrid vector + graph search.

        First finds semantically similar chunks, then expands via graph
        relationships to find structurally related code.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID.
            top_k: Number of vector search results.
            expand_graph: Whether to expand results via graph traversal.
            expansion_hops: Number of hops for graph expansion.
            max_expand: Maximum number of vector results to expand via graph.

        Returns:
            Tuple of (vector_results, graph_expanded_nodes).
        """
        return self._vector_repository.hybrid_search(
            query_embedding,
            repo_id,
            top_k,
            expand_graph,
            expansion_hops,
            max_expand,
        )

    # =========================================================================
    # Batch Operations (delegated to BatchRepository)
    # =========================================================================

    def delete_by_repo(self, repo_id: str) -> Dict[str, int]:
        """Delete all nodes and edges for a repository with counts.

        Uses batched transactions to avoid memory issues with large repositories.

        Args:
            repo_id: The repository ID to delete.

        Returns:
            Dictionary with counts of deleted nodes by type.
        """
        return self._batch_repository.delete_by_repo(repo_id)

    # Alias for consistency with router expectations
    delete_repository = delete_by_repo

    def delete_by_file(self, repo_id: str, file_path: str) -> Dict[str, int]:
        """Delete all nodes and edges for a specific file including chunks.

        Uses batched transactions to avoid memory issues with large datasets.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            Dictionary with counts of deleted nodes by type.
        """
        return self._batch_repository.delete_by_file(repo_id, file_path)

    def upsert_chunks_with_embeddings_batch(
        self,
        file_node_id: str,
        rows: List[Dict[str, Any]],
        store_content: bool = True,
        store_embedding: bool = True,
    ) -> None:
        """Batch upsert chunks with embeddings and File→Chunk CONTAINS edges.

        Uses UNWIND Cypher for efficient batch operations.

        Args:
            file_node_id: The File node ID to link chunks to.
            rows: List of dictionaries containing chunk data.
            store_content: Whether to store content property on Chunk nodes.
            store_embedding: Whether to store embedding property on Chunk nodes.
        """
        self._batch_repository.upsert_chunks_batch(
            file_node_id, rows, store_content, store_embedding
        )

    def upsert_symbol_chunk_links_batch(
        self,
        links: List[Dict[str, str]],
    ) -> None:
        """Batch upsert Symbol→Chunk REPRESENTED_BY edges.

        Args:
            links: List of dictionaries with symbol_id and chunk_id keys.
        """
        self._batch_repository.upsert_symbol_chunk_links_batch(links)

    def upsert_next_chunk_edges_batch(
        self,
        edges: List[Dict[str, str]],
    ) -> None:
        """Batch upsert Chunk→Chunk NEXT_CHUNK edges.

        Args:
            edges: List of dictionaries with from_chunk_id and to_chunk_id keys.
        """
        self._batch_repository.upsert_next_chunk_edges_batch(edges)

    # =========================================================================
    # Statistics and Architecture
    # =========================================================================

    def get_repo_stats(self, repo_id: str) -> Dict[str, int]:
        """Get statistics for a repository from the graph.

        Args:
            repo_id: The repository ID.

        Returns:
            Dictionary with counts (symbol_count, file_count, relationship_count).
        """
        stats = {
            "symbol_count": 0,
            "file_count": 0,
            "relationship_count": 0,
        }

        try:
            with self._session_manager.session() as session:
                # Count symbols
                symbol_result = session.run(
                    StatsQueries.COUNT_SYMBOLS,
                    repo_id=repo_id,
                )
                record = symbol_result.single()
                if record:
                    stats["symbol_count"] = record["cnt"]

                # Count files
                file_result = session.run(
                    StatsQueries.COUNT_FILES,
                    repo_id=repo_id,
                )
                record = file_result.single()
                if record:
                    stats["file_count"] = record["cnt"]

                # Count relationships for this repo's nodes
                rel_result = session.run(
                    StatsQueries.COUNT_RELATIONSHIPS,
                    repo_id=repo_id,
                )
                record = rel_result.single()
                if record:
                    stats["relationship_count"] = record["cnt"]

                return stats

        except Neo4jError as e:
            logger.error(f"Failed to get repo stats for {repo_id}: {e}")
            return stats

    def get_architecture(self, repo_id: str) -> ArchitectureOverview:
        """Get high-level component overview."""
        try:
            with self._session_manager.session() as session:
                modules_result = session.run(StatsQueries.GET_MODULES, repo_id=repo_id)
                modules = []
                module_counts: Dict[str, int] = {}

                for record in modules_result:
                    attrs = record["attrs"]
                    if attrs:
                        attrs_dict = self._deserialize_attrs(attrs)
                        file_path = attrs_dict.get("file_path", "")
                        parts = file_path.split("/")
                        module = parts[0] if len(parts) > 1 else "(root)"
                        module_counts[module] = module_counts.get(module, 0) + 1

                for module, count in sorted(module_counts.items(), key=lambda x: -x[1]):
                    modules.append({"name": module, "file_count": count})

                # Get edge types that actually exist in this repository (more accurate than semantic_edges)
                # This queries the database for actual relationship types
                edge_types = self._edge_repository.get_available_edge_types(repo_id)

                rel_result = session.run(
                    StatsQueries.get_relationships_query(),
                    repo_id=repo_id,
                    edge_types=edge_types
                )
                relationships = []
                for record in rel_result:
                    from_attrs = self._deserialize_attrs(record["from_file"])
                    to_attrs = self._deserialize_attrs(record["to_file"])
                    relationships.append({
                        "type": record["rel_type"],
                        "from_file": from_attrs.get("file_path", ""),
                        "to_file": to_attrs.get("file_path", ""),
                    })

                return ArchitectureOverview(
                    repo_id=repo_id,
                    modules=modules,
                    relationships=relationships,
                )
        except Neo4jError as e:
            logger.error(f"Failed to get architecture for repo {repo_id}: {e}")
            raise

    def list_files(self, repo_id: str) -> List[str]:
        """List all file paths in a repository."""
        try:
            with self._session_manager.session() as session:
                result = session.run(StatsQueries.LIST_FILES, repo_id=repo_id)
                file_paths = []
                for record in result:
                    attrs = record["attrs"]
                    if attrs:
                        attrs_dict = self._deserialize_attrs(attrs)
                        file_path = attrs_dict.get("file_path", "")
                        if file_path:
                            file_paths.append(file_path)
                return sorted(file_paths)
        except Neo4jError as e:
            logger.error(f"Failed to list files for repo {repo_id}: {e}")
            raise

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _deserialize_attrs(self, attrs_str: Optional[str]) -> Dict[str, Any]:
        """Deserialize attributes from JSON string."""
        if not attrs_str:
            return {}
        try:
            return json.loads(attrs_str)
        except (json.JSONDecodeError, TypeError):
            return {}
