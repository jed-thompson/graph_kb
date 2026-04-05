"""ChromaDB Vector Store implementation for code chunk embeddings."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..config import ChromaConfig

logger = EnhancedLogger(__name__)


@dataclass
class SearchResult:
    """Result from a vector search query."""

    chunk_id: str
    score: float
    metadata: Dict[str, Any]
    content: Optional[str] = None


class ChromaVectorStore:
    """Vector store implementation using ChromaDB."""

    def __init__(self, config: ChromaConfig):
        """Initialize the ChromaDB vector store.

        Args:
            config: ChromaDB connection configuration.
        """
        self._config = config
        self._client: Optional[chromadb.HttpClient] = None
        self._collection = None

    @property
    def client(self) -> chromadb.HttpClient:
        """Get or create the ChromaDB client."""
        if self._client is None:
            self._client = chromadb.HttpClient(
                host=self._config.host,
                port=self._config.port,
                settings=Settings(
                    anonymized_telemetry=False,
                ),
            )
        return self._client

    @property
    def collection(self):
        """Get or create the collection for code chunks."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self._config.collection_name,
                metadata={
                    "hnsw:space": "cosine",  # Use cosine similarity
                    "hnsw:construction_ef": 200,  # Higher ef for better recall during construction
                    "hnsw:M": 16,  # Number of connections per node (default is usually 16)
                    "hnsw:search_ef": 100,  # Search ef for better recall during search
                },
            )
        return self._collection

    def _refresh_collection(self) -> None:
        """Invalidate cached collection so the next access re-creates it."""
        self._collection = None

    def _is_stale_collection_error(self, error: Exception) -> bool:
        """Check if an error indicates a stale/missing collection reference."""
        msg = str(error).lower()
        return "does not exist" in msg or "404" in msg

    def _with_collection_retry(self, operation, *args, **kwargs):
        """Execute an operation on the collection, retrying once if the collection reference is stale."""
        try:
            return operation(self.collection, *args, **kwargs)
        except Exception as e:
            if self._is_stale_collection_error(e):
                logger.warning(
                    "Stale collection reference detected, refreshing and retrying"
                )
                self._refresh_collection()
                return operation(self.collection, *args, **kwargs)
            raise

    def upsert(
        self,
        chunk_id: str,
        embedding: List[float],
        metadata: Dict[str, Any],
        content: Optional[str] = None,
    ) -> None:
        """Insert or update a chunk embedding with metadata.

        Args:
            chunk_id: Unique identifier for the chunk.
            embedding: Vector embedding for the chunk.
            metadata: Metadata associated with the chunk.
            content: Optional text content of the chunk.
        """
        # Prepare metadata - ChromaDB requires flat metadata
        flat_metadata = self._flatten_metadata(metadata)

        try:
            documents = [content] if content else None
            self.collection.upsert(
                ids=[chunk_id],
                embeddings=[embedding],
                metadatas=[flat_metadata],
                documents=documents,
            )
        except Exception as e:
            if self._is_stale_collection_error(e):
                logger.warning(
                    f"Stale collection reference detected, refreshing and retrying upsert for {chunk_id}"
                )
                self._refresh_collection()
                self.collection.upsert(
                    ids=[chunk_id],
                    embeddings=[embedding],
                    metadatas=[flat_metadata],
                    documents=documents,
                )
            else:
                logger.error(f"Failed to upsert chunk {chunk_id}: {e}")
                raise

    def upsert_batch(
        self,
        chunk_ids: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        contents: Optional[List[str]] = None,
    ) -> None:
        """Insert or update multiple chunk embeddings.

        Args:
            chunk_ids: List of unique identifiers.
            embeddings: List of vector embeddings.
            metadatas: List of metadata dictionaries.
            contents: Optional list of text contents.
        """
        if not chunk_ids:
            return

        flat_metadatas = [self._flatten_metadata(m) for m in metadatas]

        try:
            self.collection.upsert(
                ids=chunk_ids,
                embeddings=embeddings,
                metadatas=flat_metadatas,
                documents=contents,
            )
        except Exception as e:
            if self._is_stale_collection_error(e):
                logger.warning(
                    f"Stale collection reference detected, refreshing and retrying batch upsert of {len(chunk_ids)} chunks"
                )
                self._refresh_collection()
                self.collection.upsert(
                    ids=chunk_ids,
                    embeddings=embeddings,
                    metadatas=flat_metadatas,
                    documents=contents,
                )
            else:
                logger.error(f"Failed to upsert batch of {len(chunk_ids)} chunks: {e}")
                raise

    def search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 10,
        filter_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Search for similar chunks by embedding, filtered by repo_id.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of results to return.
            filter_metadata: Additional metadata filters.

        Returns:
            List of SearchResult objects ordered by similarity (highest first).
        """
        # Build where clause for filtering
        # ChromaDB requires $and operator for multiple conditions
        if filter_metadata:
            conditions = [{"repo_id": repo_id}]
            for key, value in filter_metadata.items():
                conditions.append({key: value})
            where_clause = {"$and": conditions}
        else:
            where_clause = {"repo_id": repo_id}

        try:
            results = self._with_collection_retry(
                lambda col: col.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=where_clause,
                    include=["metadatas", "documents", "distances"],
                )
            )

            search_results = []
            if results and results["ids"] and results["ids"][0]:
                ids = results["ids"][0]
                distances = (
                    results["distances"][0]
                    if results.get("distances")
                    else [0] * len(ids)
                )
                metadatas = (
                    results["metadatas"][0]
                    if results.get("metadatas")
                    else [{}] * len(ids)
                )
                documents = (
                    results["documents"][0]
                    if results.get("documents")
                    else [None] * len(ids)
                )

                for i, chunk_id in enumerate(ids):
                    # Convert distance to similarity score (cosine distance to similarity)
                    # ChromaDB returns distance, lower is better
                    # For cosine: similarity = 1 - distance
                    score = 1.0 - distances[i] if distances else 0.0
                    search_results.append(
                        SearchResult(
                            chunk_id=chunk_id,
                            score=score,
                            metadata=metadatas[i] if metadatas else {},
                            content=documents[i] if documents else None,
                        )
                    )

            # Results should already be sorted by similarity (highest first)
            return search_results

        except Exception as e:
            logger.error(f"Failed to search for repo {repo_id}: {e}")
            raise

    def get(self, chunk_id: str) -> Optional[SearchResult]:
        """Get a specific chunk by ID.

        Args:
            chunk_id: The chunk ID to retrieve.

        Returns:
            SearchResult if found, None otherwise.
        """
        try:
            results = self._with_collection_retry(
                lambda col: col.get(
                    ids=[chunk_id],
                    include=["metadatas", "documents"],
                )
            )

            if results and results["ids"]:
                return SearchResult(
                    chunk_id=chunk_id,
                    score=1.0,  # Exact match
                    metadata=results["metadatas"][0]
                    if results.get("metadatas")
                    else {},
                    content=results["documents"][0]
                    if results.get("documents")
                    else None,
                )
            return None

        except Exception as e:
            logger.error(f"Failed to get chunk {chunk_id}: {e}")
            raise

    def delete(self, chunk_id: str) -> None:
        """Delete a chunk embedding.

        Args:
            chunk_id: The chunk ID to delete.
        """
        try:
            self._with_collection_retry(lambda col: col.delete(ids=[chunk_id]))
        except Exception as e:
            logger.error(f"Failed to delete chunk {chunk_id}: {e}")
            raise

    def delete_batch(self, chunk_ids: List[str]) -> None:
        """Delete multiple chunk embeddings.

        Args:
            chunk_ids: List of chunk IDs to delete.
        """
        if not chunk_ids:
            return

        try:
            self._with_collection_retry(lambda col: col.delete(ids=chunk_ids))
        except Exception as e:
            logger.error(f"Failed to delete batch of {len(chunk_ids)} chunks: {e}")
            raise

    def delete_by_file(self, repo_id: str, file_path: str) -> int:
        """Delete all chunks for a specific file.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            Count of deleted documents.
        """
        try:
            # Query for all chunks matching the file
            results = self._with_collection_retry(
                lambda col: col.get(
                    where={"$and": [{"repo_id": repo_id}, {"file_path": file_path}]},
                    include=[],
                )
            )

            deleted_count = 0
            if results and results["ids"]:
                deleted_count = len(results["ids"])
                self._with_collection_retry(lambda col: col.delete(ids=results["ids"]))
                logger.info(f"Deleted {deleted_count} chunks for file {file_path}")

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to delete chunks for file {file_path}: {e}")
            raise

    def delete_by_repo(self, repo_id: str) -> int:
        """Delete all chunks for a repository.

        Args:
            repo_id: The repository ID.

        Returns:
            Count of deleted documents.
        """
        try:
            # Query for all chunks matching the repo
            results = self._with_collection_retry(
                lambda col: col.get(
                    where={"repo_id": repo_id},
                    include=[],
                )
            )

            deleted_count = 0
            if results and results["ids"]:
                deleted_count = len(results["ids"])
                self._with_collection_retry(lambda col: col.delete(ids=results["ids"]))
                logger.info(f"Deleted {deleted_count} chunks for repo {repo_id}")

            return deleted_count

        except Exception as e:
            logger.error(f"Failed to delete chunks for repo {repo_id}: {e}")
            raise

    # Alias for consistency with router expectations
    delete_repository = delete_by_repo

    def count(self, repo_id: Optional[str] = None) -> int:
        """Count chunks in the collection.

        Args:
            repo_id: Optional repository ID to filter count.

        Returns:
            Number of chunks.
        """
        try:
            if repo_id:
                results = self._with_collection_retry(
                    lambda col: col.get(
                        where={"repo_id": repo_id},
                        include=[],
                    )
                )
                return len(results["ids"]) if results and results["ids"] else 0
            else:
                return self._with_collection_retry(lambda col: col.count())
        except Exception as e:
            logger.error(f"Failed to count chunks: {e}")
            raise

    def get_existing_chunk_ids(self, repo_id: str) -> set:
        """Get all chunk IDs that exist in the collection for a repository.

        This is useful for resume functionality to skip already-embedded chunks.

        Args:
            repo_id: Repository ID to filter by.

        Returns:
            Set of chunk IDs that exist in the collection.
        """
        try:
            results = self._with_collection_retry(
                lambda col: col.get(
                    where={"repo_id": repo_id},
                    include=[],  # Only get IDs, not embeddings or documents
                )
            )
            if results and results["ids"]:
                return set(results["ids"])
            return set()
        except Exception as e:
            logger.error(f"Failed to get existing chunk IDs for repo {repo_id}: {e}")
            raise

    def health_check(self) -> bool:
        """Check if the ChromaDB connection is healthy.

        Returns:
            True if connection is healthy, False otherwise.
        """
        try:
            # Try to get heartbeat
            self.client.heartbeat()
            return True
        except Exception as e:
            logger.error(f"ChromaDB health check failed: {e}")
            return False

    def _flatten_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten metadata for ChromaDB storage.

        ChromaDB requires flat metadata with primitive types.

        Args:
            metadata: Nested metadata dictionary.

        Returns:
            Flattened metadata dictionary.
        """
        flat = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                flat[key] = value
            elif isinstance(value, datetime):
                flat[key] = value.isoformat()
            elif isinstance(value, list):
                # Convert lists to comma-separated strings
                flat[key] = ",".join(str(v) for v in value)
            elif value is None:
                # Skip None values
                continue
            else:
                # Convert other types to string
                flat[key] = str(value)
        return flat

    def close(self) -> None:
        """Close the ChromaDB client connection."""
        # ChromaDB HttpClient doesn't require explicit closing
        self._client = None
        self._collection = None
