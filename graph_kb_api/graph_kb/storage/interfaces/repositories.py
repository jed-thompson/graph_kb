"""Repository interface protocols for graph storage operations.

This module defines Protocol interfaces for all repository types, enabling
type checking, dependency injection, and testing with mocks.
"""

from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from ...models.base import Chunk, GraphEdge, GraphNode
from ...models.enums import GraphEdgeType


@runtime_checkable
class INodeRepository(Protocol):
    """Interface for node operations.

    Defines the contract for all node CRUD operations including:
    - Creating nodes of all types (Repo, File, Symbol, Chunk, Directory)
    - Retrieving nodes by ID
    - Checking node existence
    - Deleting nodes
    - Getting chunks for files and symbols
    """

    def create(self, node: GraphNode) -> None:
        """Create a node in the graph.

        Args:
            node: The GraphNode to create.
        """
        ...

    def get_by_id(self, node_id: str) -> Optional[GraphNode]:
        """Retrieve a node by its ID.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            The GraphNode if found, None otherwise.
        """
        ...

    def exists(self, node_id: str) -> bool:
        """Check if a node exists in the graph.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            True if the node exists, False otherwise.
        """
        ...

    def delete(self, node_id: str) -> None:
        """Delete a node and its relationships from the graph.

        Args:
            node_id: The unique identifier of the node to delete.
        """
        ...

    def create_chunk(self, chunk: Chunk, embedding: List[float]) -> str:
        """Create a Chunk node with embedding for vector search.

        Args:
            chunk: The Chunk data.
            embedding: Vector embedding for the chunk.

        Returns:
            The chunk node ID.
        """
        ...

    def get_chunks_for_file(self, repo_id: str, file_path: str) -> List[GraphNode]:
        """Get all chunk nodes for a specific file.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            List of chunk GraphNode objects ordered by start_line.
        """
        ...

    def get_chunks_for_symbol(self, repo_id: str, symbol_name: str) -> List[GraphNode]:
        """Get chunks that define or reference a symbol.

        Args:
            repo_id: The repository ID.
            symbol_name: The symbol name to search for.

        Returns:
            List of chunk GraphNode objects ordered by file_path and start_line.
        """
        ...


@runtime_checkable
class IEdgeRepository(Protocol):
    """Interface for edge/relationship operations.

    Defines the contract for all edge operations including:
    - Creating edges of all types (CONTAINS, CALLS, IMPORTS, EXTENDS, etc.)
    - Retrieving neighbors with direction support
    - Finding paths between nodes
    - Getting reachable nodes within a depth limit
    """

    def create(self, edge: GraphEdge) -> None:
        """Create an edge between two nodes in the graph.

        Args:
            edge: The GraphEdge to create.
        """
        ...

    def exists(self, from_id: str, to_id: str, edge_type: GraphEdgeType) -> bool:
        """Check if an edge exists between two nodes.

        Args:
            from_id: Source node ID.
            to_id: Target node ID.
            edge_type: Type of edge to check.

        Returns:
            True if the edge exists, False otherwise.
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
            max_hops: Maximum path length (1-10).

        Returns:
            List of node IDs in the path, or None if no path exists.
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
            Tuple of (nodes, edges) where:
            - nodes: List of reachable GraphNode objects
            - edges: List of edge dictionaries with source, target, type
        """
        ...

    def find_symbols_by_kind(
        self,
        repo_id: str,
        kinds: List[str],
        folder_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find symbols by kind (function, method, class, etc.).

        Args:
            repo_id: Repository ID to search within.
            kinds: List of symbol kinds to filter by.
            folder_path: Optional folder path to filter symbols by location.

        Returns:
            List of dictionaries with 'id' and 'attrs' keys for matching symbols.
        """
        ...


@runtime_checkable
class IVectorRepository(Protocol):
    """Interface for vector search operations.

    Defines the contract for all vector search operations including:
    - Vector index creation and management
    - Vector similarity search
    - Hybrid search (vector + graph expansion)
    """

    def search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 500,
        min_score: float = 0.0,
    ) -> List[Any]:
        """Search for similar chunks using Neo4j vector index.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of VectorSearchResult ordered by similarity (descending).
        """
        ...

    def hybrid_search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 200,
        expand_graph: bool = True,
        expansion_hops: int = 1,
    ) -> Tuple[List[Any], List[GraphNode]]:
        """Perform hybrid vector + graph search.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID.
            top_k: Number of vector search results.
            expand_graph: Whether to expand results via graph traversal.
            expansion_hops: Number of hops for graph expansion.

        Returns:
            Tuple of (vector_results, graph_expanded_nodes).
        """
        ...

    def ensure_index(
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
        """
        ...


@runtime_checkable
class IBatchRepository(Protocol):
    """Interface for batch operations.

    Defines the contract for all bulk/batch operations including:
    - Bulk node creation
    - Bulk edge creation
    - Repository-level deletion
    - File-level deletion
    - Batch upsert of chunks with embeddings
    """

    def delete_by_repo(self, repo_id: str) -> Dict[str, int]:
        """Delete all nodes and edges for a repository with counts.

        Args:
            repo_id: The repository ID to delete.

        Returns:
            Dictionary with counts of deleted nodes by type.
        """
        ...

    def delete_by_file(self, repo_id: str, file_path: str) -> Dict[str, int]:
        """Delete all nodes and edges for a specific file.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            Dictionary with counts of deleted nodes by type.
        """
        ...

    def upsert_chunks_batch(
        self,
        file_node_id: str,
        rows: List[Dict[str, Any]],
        store_content: bool = True,
        store_embedding: bool = True,
    ) -> None:
        """Batch upsert chunks with embeddings and File→Chunk CONTAINS edges.

        Args:
            file_node_id: The File node ID to link chunks to.
            rows: List of dictionaries containing chunk data.
            store_content: Whether to store content property on Chunk nodes.
            store_embedding: Whether to store embedding property on Chunk nodes.
        """
        ...
