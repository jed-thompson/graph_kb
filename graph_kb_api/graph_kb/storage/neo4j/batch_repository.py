"""Batch repository for Neo4j graph operations.

This module provides the BatchRepository class for handling all bulk/batch
operations in the Neo4j graph database.
"""

import json
from typing import Any, Dict, List, Optional

from neo4j.exceptions import Neo4jError

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.base import GraphEdge, GraphNode
from .connection import SessionManager
from .queries import BatchQueries, NodeQueries

logger = EnhancedLogger(__name__)


class BatchRepository:
    """Repository for batch/bulk operations.

    This class handles all bulk operations including:
    - Bulk node creation with configurable batch sizes
    - Bulk edge creation
    - Repository-level deletion with progress tracking
    - File-level deletion
    - Batch upsert of chunks with embeddings

    All operations use the SessionManager for database access and
    reference queries from the centralized queries module.
    """

    DEFAULT_BATCH_SIZE = 1000

    def __init__(self, session_manager: SessionManager):
        """Initialize the BatchRepository.

        Args:
            session_manager: SessionManager instance for database operations.
        """
        self._session_manager = session_manager

    def bulk_create_nodes(
        self,
        nodes: List[GraphNode],
        batch_size: Optional[int] = None,
    ) -> int:
        """Create multiple nodes in batches.

        Args:
            nodes: List of GraphNode objects to create.
            batch_size: Number of nodes per batch (default: DEFAULT_BATCH_SIZE).

        Returns:
            Number of nodes created.

        Raises:
            Neo4jError: If bulk creation fails.
        """
        if not nodes:
            return 0

        batch_size = batch_size or self.DEFAULT_BATCH_SIZE
        created_count = 0

        try:
            with self._session_manager.session() as session:
                # Process nodes in batches
                for i in range(0, len(nodes), batch_size):
                    batch = nodes[i:i + batch_size]

                    for node in batch:
                        label = node.type.value

                        # Select query based on whether node has embedding
                        if node.embedding is not None:
                            query = NodeQueries.CREATE_NODE_WITH_EMBEDDING.format(label=label)
                            params = {
                                "id": node.id,
                                "repo_id": node.repo_id,
                                "attrs": self._serialize_attrs(node.attrs),
                                "summary": node.summary,
                                "embedding": node.embedding,
                            }
                        else:
                            query = NodeQueries.CREATE_NODE.format(label=label)
                            params = {
                                "id": node.id,
                                "repo_id": node.repo_id,
                                "attrs": self._serialize_attrs(node.attrs),
                                "summary": node.summary,
                            }

                        session.run(query, **params)
                        created_count += 1

                    logger.debug(
                        f"Batch created {len(batch)} nodes "
                        f"({created_count}/{len(nodes)} total)"
                    )

            logger.info(f"Bulk created {created_count} nodes")
            return created_count

        except Neo4jError as e:
            logger.error(f"Failed to bulk create nodes: {e}")
            raise

    def bulk_create_edges(
        self,
        edges: List[GraphEdge],
        batch_size: Optional[int] = None,
    ) -> int:
        """Create multiple edges in batches.

        Args:
            edges: List of GraphEdge objects to create.
            batch_size: Number of edges per batch (default: DEFAULT_BATCH_SIZE).

        Returns:
            Number of edges created.

        Raises:
            Neo4jError: If bulk creation fails.
        """
        if not edges:
            return 0

        batch_size = batch_size or self.DEFAULT_BATCH_SIZE
        created_count = 0

        try:
            with self._session_manager.session() as session:
                # Process edges in batches
                for i in range(0, len(edges), batch_size):
                    batch = edges[i:i + batch_size]

                    for edge in batch:
                        edge_type = edge.edge_type.value
                        # Use centralized query from EdgeQueries
                        from .queries import EdgeQueries
                        query = EdgeQueries.CREATE_EDGE.format(edge_type=edge_type)

                        session.run(
                            query,
                            from_id=edge.from_node,
                            to_id=edge.to_node,
                            edge_id=edge.id,
                            attrs=self._serialize_attrs(edge.attrs),
                        )
                        created_count += 1

                    logger.debug(
                        f"Batch created {len(batch)} edges "
                        f"({created_count}/{len(edges)} total)"
                    )

            logger.info(f"Bulk created {created_count} edges")
            return created_count

        except Neo4jError as e:
            logger.error(f"Failed to bulk create edges: {e}")
            raise

    def delete_by_repo(self, repo_id: str) -> Dict[str, int]:
        """Delete all nodes and edges for a repository with counts.

        Deletes all nodes (Chunk, Symbol, File, Directory, Repo) and their
        associated edges for the specified repository.

        Uses batched transactions to avoid memory issues with large repositories.

        Args:
            repo_id: The repository ID to delete.

        Returns:
            Dictionary with counts of deleted nodes by type:
            - chunks_deleted: Number of Chunk nodes deleted
            - symbols_deleted: Number of Symbol nodes deleted
            - files_deleted: Number of File nodes deleted
            - directories_deleted: Number of Directory nodes deleted
            - repo_deleted: 1 if Repo node was deleted, 0 otherwise
            - total_deleted: Total count of all deleted nodes

        Raises:
            Neo4jError: If deletion fails.
        """
        counts = {
            "chunks_deleted": 0,
            "symbols_deleted": 0,
            "files_deleted": 0,
            "directories_deleted": 0,
            "repo_deleted": 0,
            "total_deleted": 0,
        }

        try:
            with self._session_manager.session() as session:
                # Count and delete Chunks in batches
                chunk_count = session.run(
                    BatchQueries.COUNT_CHUNKS_FOR_REPO,
                    repo_id=repo_id,
                ).single()
                if chunk_count:
                    counts["chunks_deleted"] = chunk_count["cnt"]

                # Delete chunks in batched transactions
                session.run(
                    BatchQueries.DELETE_CHUNKS_FOR_REPO_BATCH,
                    repo_id=repo_id,
                )

                # Count and delete Symbols in batches
                symbol_count = session.run(
                    BatchQueries.COUNT_SYMBOLS_FOR_REPO,
                    repo_id=repo_id,
                ).single()
                if symbol_count:
                    counts["symbols_deleted"] = symbol_count["cnt"]

                session.run(
                    BatchQueries.DELETE_SYMBOLS_FOR_REPO_BATCH,
                    repo_id=repo_id,
                )

                # Count and delete Files in batches
                file_count = session.run(
                    BatchQueries.COUNT_FILES_FOR_REPO,
                    repo_id=repo_id,
                ).single()
                if file_count:
                    counts["files_deleted"] = file_count["cnt"]

                session.run(
                    BatchQueries.DELETE_FILES_FOR_REPO_BATCH,
                    repo_id=repo_id,
                )

                # Count and delete Directories in batches
                dir_count = session.run(
                    BatchQueries.COUNT_DIRECTORIES_FOR_REPO,
                    repo_id=repo_id,
                ).single()
                if dir_count:
                    counts["directories_deleted"] = dir_count["cnt"]

                session.run(
                    BatchQueries.DELETE_DIRECTORIES_FOR_REPO_BATCH,
                    repo_id=repo_id,
                )

                # Delete Repo node (typically just 1, no batching needed)
                result = session.run(
                    BatchQueries.DELETE_REPO_NODE,
                    repo_id=repo_id,
                )
                record = result.single()
                if record:
                    counts["repo_deleted"] = record["cnt"]

                counts["total_deleted"] = (
                    counts["chunks_deleted"]
                    + counts["symbols_deleted"]
                    + counts["files_deleted"]
                    + counts["directories_deleted"]
                    + counts["repo_deleted"]
                )

                logger.info(
                    f"Deleted repo {repo_id}: {counts['chunks_deleted']} chunks, "
                    f"{counts['symbols_deleted']} symbols, {counts['files_deleted']} files, "
                    f"{counts['directories_deleted']} directories, {counts['repo_deleted']} repo"
                )

                return counts

        except Neo4jError as e:
            logger.error(f"Failed to delete repo {repo_id}: {e}")
            raise

    def delete_by_file(self, repo_id: str, file_path: str) -> Dict[str, int]:
        """Delete all nodes and edges for a specific file including chunks.

        Deletes chunks (by file_path property), symbols (via File→Symbol CONTAINS edges),
        and the File node itself. Also removes NEXT_CHUNK edges between chunks.

        Uses batched transactions to avoid memory issues with large datasets.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            Dictionary with counts of deleted nodes by type:
            - chunks_deleted: Number of Chunk nodes deleted
            - symbols_deleted: Number of Symbol nodes deleted
            - file_deleted: 1 if File node was deleted, 0 otherwise

        Raises:
            Neo4jError: If deletion fails.
        """
        counts = {
            "chunks_deleted": 0,
            "symbols_deleted": 0,
            "file_deleted": 0,
        }

        try:
            with self._session_manager.session() as session:
                # Count chunks first, then delete in batches
                result = session.run(
                    BatchQueries.COUNT_CHUNKS_FOR_FILE,
                    repo_id=repo_id,
                    file_path=file_path,
                )
                record = result.single()
                if record:
                    counts["chunks_deleted"] = record["cnt"]

                # Delete Chunks in batched transactions
                session.run(
                    BatchQueries.DELETE_CHUNKS_FOR_FILE_BATCH,
                    repo_id=repo_id,
                    file_path=file_path,
                )

                # Count symbols first
                file_path_pattern = f'"file_path": "{file_path}"'
                result = session.run(
                    BatchQueries.COUNT_SYMBOLS_FOR_FILE,
                    repo_id=repo_id,
                    file_path_pattern=file_path_pattern,
                )
                record = result.single()
                if record:
                    counts["symbols_deleted"] = record["cnt"]

                # Delete Symbols in batched transactions
                session.run(
                    BatchQueries.DELETE_SYMBOLS_FOR_FILE_BATCH,
                    repo_id=repo_id,
                    file_path_pattern=file_path_pattern,
                )

                # Delete the File node itself (typically just 1, no batching needed)
                result = session.run(
                    BatchQueries.DELETE_FILE_NODE,
                    repo_id=repo_id,
                    file_path_pattern=file_path_pattern,
                )
                record = result.single()
                if record:
                    counts["file_deleted"] = record["cnt"]

                logger.info(
                    f"Deleted file {file_path}: {counts['chunks_deleted']} chunks, "
                    f"{counts['symbols_deleted']} symbols, {counts['file_deleted']} file"
                )

                return counts

        except Neo4jError as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            raise

    def upsert_chunks_batch(
        self,
        file_node_id: str,
        rows: List[Dict[str, Any]],
        store_content: bool = True,
        store_embedding: bool = True,
    ) -> None:
        """Batch upsert chunks with embeddings and File→Chunk CONTAINS edges.

        Uses UNWIND Cypher for efficient batch operations. Creates Chunk nodes
        with all properties and File→Chunk CONTAINS edges in the same transaction.

        Args:
            file_node_id: The File node ID to link chunks to.
            rows: List of dictionaries containing chunk data with keys:
                - id: Chunk node ID (pattern: "{repo_id}:chunk:{chunk_id}")
                - repo_id: Repository identifier
                - chunk_id: Raw chunk ID (matches ChromaDB)
                - file_path: Path to source file
                - language: Programming language
                - start_line: Starting line number
                - end_line: Ending line number
                - commit_sha: Commit identifier
                - chunk_type: Chunk classification (code, docstring, etc.)
                - token_count: Token count
                - symbols_defined: List of symbol names defined in chunk
                - symbols_referenced: List of symbol names referenced in chunk
                - ts_indexed: ISO8601 timestamp
                - content: (optional) Chunk content text
                - embedding: (optional) Vector embedding as list of floats
            store_content: Whether to store content property on Chunk nodes.
            store_embedding: Whether to store embedding property on Chunk nodes.

        Raises:
            Neo4jError: If batch upsert fails.
        """
        if not rows:
            return

        # Build the SET clause dynamically based on config flags
        set_clause = BatchQueries.build_upsert_chunks_set_clause(
            store_content=store_content,
            store_embedding=store_embedding,
        )

        # Create chunks and File→Chunk CONTAINS edges using batched transactions
        query = BatchQueries.UPSERT_CHUNKS_BATCH.format(set_clause=set_clause)

        try:
            with self._session_manager.session() as session:
                session.run(query, rows=rows, file_node_id=file_node_id)
                logger.debug(
                    f"Batch upserted {len(rows)} chunks for file {file_node_id}"
                )
        except Neo4jError as e:
            logger.error(f"Failed to batch upsert chunks: {e}")
            raise

    def upsert_symbol_chunk_links_batch(
        self,
        links: List[Dict[str, str]],
    ) -> None:
        """Batch upsert Symbol→Chunk REPRESENTED_BY edges.

        Uses UNWIND Cypher for efficient batch edge creation. Matches existing
        Symbol and Chunk nodes and creates REPRESENTED_BY edges.

        Args:
            links: List of dictionaries with keys:
                - symbol_id: Symbol node ID
                - chunk_id: Chunk node ID

        Raises:
            Neo4jError: If batch upsert fails.
        """
        if not links:
            return

        try:
            with self._session_manager.session() as session:
                session.run(BatchQueries.UPSERT_SYMBOL_CHUNK_LINKS_BATCH, links=links)
                logger.debug(f"Batch upserted {len(links)} symbol-chunk links")
        except Neo4jError as e:
            logger.error(f"Failed to batch upsert symbol-chunk links: {e}")
            raise

    def upsert_next_chunk_edges_batch(
        self,
        edges: List[Dict[str, str]],
    ) -> None:
        """Batch upsert Chunk→Chunk NEXT_CHUNK edges.

        Uses UNWIND Cypher for efficient batch edge creation. Creates sequential
        ordering edges between chunks within the same file.

        Args:
            edges: List of dictionaries with keys:
                - from_chunk_id: Source Chunk node ID
                - to_chunk_id: Target Chunk node ID

        Raises:
            Neo4jError: If batch upsert fails.
        """
        if not edges:
            return

        try:
            with self._session_manager.session() as session:
                session.run(BatchQueries.UPSERT_NEXT_CHUNK_EDGES_BATCH, edges=edges)
                logger.debug(f"Batch upserted {len(edges)} NEXT_CHUNK edges")
        except Neo4jError as e:
            logger.error(f"Failed to batch upsert NEXT_CHUNK edges: {e}")
            raise

    def _serialize_attrs(self, attrs: Dict[str, Any]) -> str:
        """Serialize attributes dictionary to JSON string.

        Args:
            attrs: Dictionary of attributes.

        Returns:
            JSON string representation.
        """
        return json.dumps(attrs)
