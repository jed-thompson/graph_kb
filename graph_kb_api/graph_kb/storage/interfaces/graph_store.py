"""Abstract interface for graph storage operations.

This module defines the IGraphStore protocol that all graph storage
implementations must follow. It enables:
- Easy mocking for unit tests
- Potential backend swapping (e.g., Neo4j to another graph DB)
- Clear contract for graph operations
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from ...models.base import Chunk, GraphEdge, GraphNode


@dataclass
class VectorSearchResult:
    """Result from a vector similarity search in the graph store.

    Attributes:
        node_id: The unique identifier of the chunk node.
        score: Similarity score from the vector search.
        node: The full GraphNode object with all attributes.
        content: Optional content of the chunk.
        file_path: Path to the source file containing this chunk.
        start_line: Starting line number of the chunk in the source file.
        end_line: Ending line number of the chunk in the source file.
    """

    node_id: str
    score: float
    node: GraphNode
    content: Optional[str] = None
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None


@dataclass
class ArchitectureOverview:
    """High-level architecture overview of a repository.

    Attributes:
        repo_id: The repository identifier.
        modules: List of module information dictionaries.
        relationships: List of relationship information dictionaries.
    """

    repo_id: str
    modules: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]


@runtime_checkable
class IGraphStore(Protocol):
    """Abstract interface for graph storage operations.

    This protocol defines the contract for all graph storage implementations.
    Implementations must provide methods for:
    - Node CRUD operations (create, read, update, delete)
    - Edge CRUD operations
    - Vector search operations
    - Batch operations
    - Lifecycle management
    """

    # =========================================================================
    # Node Operations
    # =========================================================================

    def create_node(self, node: GraphNode) -> None:
        """Create a node in the graph.

        Args:
            node: The GraphNode to create.

        Raises:
            Exception: If node creation fails.
        """
        ...

    def create_chunk_node(self, chunk: Chunk, embedding: List[float]) -> str:
        """Create a Chunk node with embedding for vector search.

        Args:
            chunk: The Chunk data.
            embedding: Vector embedding for the chunk.

        Returns:
            The chunk node ID.

        Raises:
            Exception: If chunk creation fails.
        """
        ...

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get a node by ID from the graph.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            The GraphNode if found, None otherwise.

        Raises:
            Exception: If retrieval fails.
        """
        ...

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists in the graph.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            True if the node exists, False otherwise.

        Raises:
            Exception: If the check fails.
        """
        ...

    def delete_node(self, node_id: str) -> None:
        """Delete a node and its relationships from the graph.

        Args:
            node_id: The unique identifier of the node to delete.

        Raises:
            Exception: If deletion fails.
        """
        ...

    def get_chunks_for_file(self, repo_id: str, file_path: str) -> List[GraphNode]:
        """Get all chunk nodes for a specific file.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            List of chunk GraphNode objects ordered by start_line.

        Raises:
            Exception: If retrieval fails.
        """
        ...

    def get_chunks_for_symbol(self, repo_id: str, symbol_name: str) -> List[GraphNode]:
        """Get chunks that define or reference a symbol.

        Args:
            repo_id: The repository ID.
            symbol_name: The symbol name to search for.

        Returns:
            List of chunk GraphNode objects.

        Raises:
            Exception: If retrieval fails.
        """
        ...

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

        Raises:
            Exception: If retrieval fails.
        """
        ...

    # =========================================================================
    # Edge Operations
    # =========================================================================

    def create_edge(self, edge: GraphEdge) -> None:
        """Create a relationship between nodes in the graph.

        Args:
            edge: The GraphEdge to create.

        Raises:
            Exception: If edge creation fails.
        """
        ...

    def edge_exists(self, from_id: str, to_id: str, edge_type: str) -> bool:
        """Check if an edge exists between two nodes.

        Args:
            from_id: Source node ID.
            to_id: Target node ID.
            edge_type: The type of edge.

        Returns:
            True if the edge exists, False otherwise.

        Raises:
            Exception: If the check fails.
        """
        ...

    def link_symbol_to_chunk(
        self,
        symbol_node_id: str,
        chunk_node_id: str,
    ) -> None:
        """Create REPRESENTED_BY edge from Symbol to Chunk.

        Args:
            symbol_node_id: Symbol node ID.
            chunk_node_id: Chunk node ID.

        Raises:
            Exception: If linking fails.
        """
        ...

    def link_file_to_chunk(
        self,
        file_node_id: str,
        chunk_node_id: str,
    ) -> None:
        """Create CONTAINS edge from File to Chunk.

        Args:
            file_node_id: File node ID.
            chunk_node_id: Chunk node ID.

        Raises:
            Exception: If linking fails.
        """
        ...

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
            Exception: If retrieval fails.
        """
        ...

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

        Raises:
            ValueError: If max_depth is out of range.
            Exception: If retrieval fails.
        """
        ...

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

        Raises:
            Exception: If path finding fails.
        """
        ...

    # =========================================================================
    # Vector Operations
    # =========================================================================

    def ensure_indexes(self) -> None:
        """Create indexes including vector index for semantic search.

        Raises:
            Exception: If index creation fails.
        """
        ...

    def ensure_chunk_vector_index(
        self,
        index_name: Optional[str] = None,
        dimensions: Optional[int] = None,
        similarity: Optional[str] = None,
    ) -> None:
        """Create vector index for chunk embeddings if it doesn't exist.

        Args:
            index_name: Name of the vector index.
            dimensions: Embedding dimensions.
            similarity: Similarity function - 'cosine' or 'euclidean'.

        Raises:
            ValueError: If similarity function is invalid.
            Exception: If index creation fails.
        """
        ...

    def vector_search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> List[VectorSearchResult]:
        """Search for similar chunks using vector index.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of VectorSearchResult ordered by similarity (descending).

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
            Exception: If search fails.
        """
        ...

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

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
            Exception: If search fails.
        """
        ...

    # =========================================================================
    # Batch Operations
    # =========================================================================

    def delete_by_repo(self, repo_id: str) -> Dict[str, int]:
        """Delete all nodes and edges for a repository with counts.

        Uses batched transactions to avoid memory issues with large repositories.

        Args:
            repo_id: The repository ID to delete.

        Returns:
            Dictionary with counts of deleted nodes by type.

        Raises:
            Exception: If deletion fails.
        """
        ...

    def delete_by_file(self, repo_id: str, file_path: str) -> Dict[str, int]:
        """Delete all nodes and edges for a specific file including chunks.

        Uses batched transactions to avoid memory issues with large datasets.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            Dictionary with counts of deleted nodes by type.

        Raises:
            Exception: If deletion fails.
        """
        ...

    def upsert_chunks_with_embeddings_batch(
        self,
        file_node_id: str,
        rows: List[Dict[str, Any]],
        store_content: bool = True,
        store_embedding: bool = True,
    ) -> None:
        """Batch upsert chunks with embeddings and File→Chunk CONTAINS edges.

        Uses UNWIND for efficient batch operations.

        Args:
            file_node_id: The File node ID to link chunks to.
            rows: List of dictionaries containing chunk data.
            store_content: Whether to store content property on Chunk nodes.
            store_embedding: Whether to store embedding property on Chunk nodes.

        Raises:
            Exception: If batch upsert fails.
        """
        ...

    def upsert_symbol_chunk_links_batch(
        self,
        links: List[Dict[str, str]],
    ) -> None:
        """Batch upsert Symbol→Chunk REPRESENTED_BY edges.

        Args:
            links: List of dictionaries with symbol_id and chunk_id keys.

        Raises:
            Exception: If batch upsert fails.
        """
        ...

    def upsert_next_chunk_edges_batch(
        self,
        edges: List[Dict[str, str]],
    ) -> None:
        """Batch upsert Chunk→Chunk NEXT_CHUNK edges.

        Args:
            edges: List of dictionaries with from_chunk_id and to_chunk_id keys.

        Raises:
            Exception: If batch upsert fails.
        """
        ...

    # =========================================================================
    # Statistics and Architecture
    # =========================================================================

    def get_repo_stats(self, repo_id: str) -> Dict[str, int]:
        """Get statistics for a repository from the graph.

        Args:
            repo_id: The repository ID.

        Returns:
            Dictionary with counts (symbol_count, file_count, relationship_count).

        Raises:
            Exception: If retrieval fails.
        """
        ...

    def get_architecture(self, repo_id: str) -> ArchitectureOverview:
        """Get high-level component overview.

        Args:
            repo_id: The repository ID.

        Returns:
            ArchitectureOverview with modules and relationships.

        Raises:
            Exception: If retrieval fails.
        """
        ...

    def list_files(self, repo_id: str) -> List[str]:
        """List all file paths in a repository.

        Args:
            repo_id: The repository ID.

        Returns:
            Sorted list of file paths.

        Raises:
            Exception: If retrieval fails.
        """
        ...

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def close(self) -> None:
        """Close the graph store connection and release resources."""
        ...

    def health_check(self) -> bool:
        """Check if the graph store connection is healthy.

        Returns:
            True if healthy, False otherwise.
        """
        ...
