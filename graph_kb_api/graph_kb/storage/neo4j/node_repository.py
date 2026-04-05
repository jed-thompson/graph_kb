"""Node repository for Neo4j graph operations.

This module provides the NodeRepository class for handling all node CRUD
operations in the Neo4j graph database.
"""

import json
from typing import Any, Dict, List, Optional

from neo4j.exceptions import Neo4jError

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.base import Chunk, GraphNode
from ...models.enums import GraphNodeType
from .connection import SessionManager
from .queries import NodeQueries

logger = EnhancedLogger(__name__)


class NodeRepository:
    """Repository for graph node operations.

    This class handles all node CRUD operations including:
    - Creating nodes of all types (Repo, File, Symbol, Chunk, Directory)
    - Retrieving nodes by ID
    - Checking node existence
    - Deleting nodes
    - Getting chunks for files and symbols

    All operations use the SessionManager for database access and
    reference queries from the centralized queries module.
    """

    def __init__(self, session_manager: SessionManager):
        """Initialize the NodeRepository.

        Args:
            session_manager: SessionManager instance for database operations.
        """
        self._session_manager = session_manager

    def create(self, node: GraphNode) -> None:
        """Create a node in the graph.

        Creates a node with the appropriate label based on node type.
        If the node has an embedding, it will be stored as well.

        Args:
            node: The GraphNode to create.

        Raises:
            Neo4jError: If node creation fails.
        """
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

        try:
            with self._session_manager.session() as session:
                session.run(query, **params)
        except Neo4jError as e:
            logger.error(f"Failed to create node {node.id}: {e}")
            raise

    def create_chunk(self, chunk: Chunk, embedding: List[float]) -> str:
        """Create a Chunk node with embedding for vector search.

        Args:
            chunk: The Chunk data.
            embedding: Vector embedding for the chunk.

        Returns:
            The chunk node ID.

        Raises:
            Neo4jError: If chunk creation fails.
        """
        chunk_node_id = f"{chunk.repo_id}:chunk:{chunk.chunk_id}"

        try:
            with self._session_manager.session() as session:
                session.run(
                    NodeQueries.CREATE_CHUNK_NODE,
                    id=chunk_node_id,
                    repo_id=chunk.repo_id,
                    file_path=chunk.file_path,
                    language=chunk.language.value,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    symbols_defined=",".join(chunk.symbols_defined),
                    symbols_referenced=",".join(chunk.symbols_referenced),
                    commit_sha=chunk.commit_sha,
                    chunk_type=chunk.chunk_type,
                    token_count=chunk.token_count or 0,
                    embedding=embedding,
                )
            return chunk_node_id
        except Neo4jError as e:
            logger.error(f"Failed to create chunk node {chunk_node_id}: {e}")
            raise

    def get_by_id(self, node_id: str) -> Optional[GraphNode]:
        """Retrieve a node by its ID.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            The GraphNode if found, None otherwise.

        Raises:
            Neo4jError: If retrieval fails.
        """
        try:
            with self._session_manager.session() as session:
                result = session.run(NodeQueries.GET_NODE_BY_ID, id=node_id)
                record = result.single()
                if record:
                    return self._record_to_node(record)
                return None
        except Neo4jError as e:
            logger.error(f"Failed to get node {node_id}: {e}")
            raise

    def exists(self, node_id: str) -> bool:
        """Check if a node exists in the graph.

        Args:
            node_id: The unique identifier of the node.

        Returns:
            True if the node exists, False otherwise.

        Raises:
            Neo4jError: If the check fails.
        """
        try:
            with self._session_manager.session() as session:
                result = session.run(NodeQueries.NODE_EXISTS, id=node_id)
                record = result.single()
                return record["exists"] if record else False
        except Neo4jError as e:
            logger.error(f"Failed to check node existence {node_id}: {e}")
            raise

    def delete(self, node_id: str) -> None:
        """Delete a node and its relationships from the graph.

        Args:
            node_id: The unique identifier of the node to delete.

        Raises:
            Neo4jError: If deletion fails.
        """
        try:
            with self._session_manager.session() as session:
                session.run(NodeQueries.DELETE_NODE, id=node_id)
        except Neo4jError as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            raise

    def get_chunks_for_file(self, repo_id: str, file_path: str) -> List[GraphNode]:
        """Get all chunk nodes for a specific file.

        Args:
            repo_id: The repository ID.
            file_path: The file path within the repository.

        Returns:
            List of chunk GraphNode objects ordered by start_line.

        Raises:
            Neo4jError: If retrieval fails.
        """
        try:
            with self._session_manager.session() as session:
                result = session.run(
                    NodeQueries.GET_CHUNKS_FOR_FILE,
                    repo_id=repo_id,
                    file_path=file_path,
                )
                return [self._record_to_node(record) for record in result]
        except Neo4jError as e:
            logger.error(f"Failed to get chunks for file {file_path}: {e}")
            raise

    def get_chunks_for_symbol(self, repo_id: str, symbol_name: str) -> List[GraphNode]:
        """Get chunks that define or reference a symbol.

        Args:
            repo_id: The repository ID.
            symbol_name: The symbol name to search for.

        Returns:
            List of chunk GraphNode objects ordered by file_path and start_line.

        Raises:
            Neo4jError: If retrieval fails.
        """
        try:
            with self._session_manager.session() as session:
                result = session.run(
                    NodeQueries.GET_CHUNKS_FOR_SYMBOL,
                    repo_id=repo_id,
                    symbol_name=symbol_name,
                )
                return [self._record_to_node(record) for record in result]
        except Neo4jError as e:
            logger.error(f"Failed to get chunks for symbol {symbol_name}: {e}")
            raise

    def get_chunk_with_context(
        self,
        chunk_id: str,
        include_neighbors: bool = True,
    ) -> tuple[Optional[GraphNode], List[GraphNode]]:
        """Get a chunk node with its graph context.

        Args:
            chunk_id: Chunk node ID.
            include_neighbors: Whether to include neighboring chunks/symbols.

        Returns:
            Tuple of (chunk_node, context_nodes).

        Raises:
            Neo4jError: If retrieval fails.
        """
        chunk = self.get_by_id(chunk_id)
        if not chunk:
            return None, []

        if not include_neighbors:
            return chunk, []

        # Get related symbols and adjacent chunks
        context_nodes = []
        try:
            with self._session_manager.session() as session:
                result = session.run(NodeQueries.GET_CHUNK_WITH_CONTEXT, chunk_id=chunk_id)
                record = result.single()
                if record:
                    for node_list in [
                        record["symbols"],
                        record["next_chunks"],
                        record["prev_chunks"],
                    ]:
                        for node_data in node_list:
                            if node_data:
                                context_nodes.append(self._node_data_to_graph_node(node_data))
        except Neo4jError as e:
            logger.warning(f"Failed to get chunk context: {e}")

        return chunk, context_nodes

    def _record_to_node(self, record) -> GraphNode:
        """Convert a Neo4j record to a GraphNode.

        Args:
            record: Neo4j record with 'n' (node) and 'labels' fields.

        Returns:
            GraphNode instance.
        """
        node_data = record["n"]
        labels = record["labels"]

        # Determine node type from labels
        node_type = GraphNodeType.SYMBOL  # Default
        for label in labels:
            try:
                node_type = GraphNodeType(label)
                break
            except ValueError:
                continue

        attrs = self._deserialize_attrs(node_data.get("attrs", "{}"))

        # For Chunk nodes, attrs are stored directly on the node
        if node_type == GraphNodeType.CHUNK:
            attrs = {
                "file_path": node_data.get("file_path"),
                "start_line": node_data.get("start_line"),
                "end_line": node_data.get("end_line"),
                "language": node_data.get("language"),
                "content": node_data.get("content"),
                "symbols_defined": self._parse_symbols_list(
                    node_data.get("symbols_defined", "")
                ),
                "symbols_referenced": self._parse_symbols_list(
                    node_data.get("symbols_referenced", "")
                ),
            }

        return GraphNode(
            id=node_data.get("id", ""),
            type=node_type,
            repo_id=node_data.get("repo_id", ""),
            attrs=attrs,
            summary=node_data.get("summary"),
        )

    def _node_data_to_graph_node(self, node_data) -> GraphNode:
        """Convert raw node data to GraphNode.

        Args:
            node_data: Raw node data dictionary from Neo4j.

        Returns:
            GraphNode instance.
        """
        return GraphNode(
            id=node_data.get("id", ""),
            type=GraphNodeType.SYMBOL,
            repo_id=node_data.get("repo_id", ""),
            attrs=self._deserialize_attrs(node_data.get("attrs", "{}")),
            summary=node_data.get("summary"),
        )

    def _serialize_attrs(self, attrs: Dict[str, Any]) -> str:
        """Serialize attributes dictionary to JSON string.

        Args:
            attrs: Dictionary of attributes.

        Returns:
            JSON string representation.
        """
        return json.dumps(attrs)

    def _deserialize_attrs(self, attrs_str: Optional[str]) -> Dict[str, Any]:
        """Deserialize attributes from JSON string.

        Args:
            attrs_str: JSON string of attributes.

        Returns:
            Dictionary of attributes.
        """
        if not attrs_str:
            return {}
        try:
            return json.loads(attrs_str)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _parse_symbols_list(self, value) -> list:
        """Parse symbols_defined or symbols_referenced from string or list.

        Args:
            value: Either a string (comma-separated) or a list.

        Returns:
            List of symbol strings.
        """
        if value is None:
            return []
        if isinstance(value, list):
            return [s.strip() if isinstance(s, str) else str(s) for s in value if s]
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return []
