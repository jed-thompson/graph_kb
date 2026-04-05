"""Vector repository for Neo4j graph operations.

This module provides the VectorRepository class for handling all vector search
operations in the Neo4j graph database.
"""

from typing import Any, Dict, List, Optional, Tuple, cast

from neo4j.exceptions import Neo4jError
from typing_extensions import LiteralString

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.base import GraphNode
from ...models.enums import GraphEdgeType, GraphNodeType
from .connection import SessionManager
from .models import UnifiedRAGResult
from .queries import EdgeQueries, IndexQueries, TraversalQueries, VectorQueries

logger = EnhancedLogger(__name__)


class VectorIndexNotAvailableError(Exception):
    """Raised when the Neo4j vector index is not available.

    This exception is raised when:
    - The vector index does not exist
    - The vector index is not ONLINE (still building)
    - Neo4j version doesn't support vector indexes
    """
    pass


class APOCNotAvailableError(Exception):
    """Raised when APOC procedures are not available in Neo4j.

    This exception is raised when:
    - APOC library is not installed
    - APOC procedures are not accessible

    APOC is required for JSON parsing in unified RAG queries.
    Install APOC by following: https://neo4j.com/labs/apoc/
    """
    pass


class VectorSearchResult:
    """Result from a vector similarity search in Neo4j.

    Attributes:
        node_id: The unique identifier of the chunk node (id property).
        score: Similarity score from the vector search.
        node: The full GraphNode object with all attributes.
        content: Optional content of the chunk.
        file_path: Path to the source file containing this chunk.
        start_line: Starting line number of the chunk in the source file.
        end_line: Ending line number of the chunk in the source file.
        is_documentation: True if this chunk is from a markdown documentation file.
    """

    def __init__(
        self,
        node_id: str,
        score: float,
        node: GraphNode,
        content: Optional[str] = None,
        file_path: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        is_documentation: bool = False,
    ):
        self.node_id = node_id
        self.score = score
        self.node = node
        self.content = content
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.is_documentation = is_documentation


class VectorRepository:
    """Repository for vector search operations.

    This class handles all vector search operations including:
    - Vector index creation and management
    - Vector similarity search
    - Hybrid search (vector + graph expansion)

    All operations use the SessionManager for database access and
    reference queries from the centralized queries module.
    """

    VECTOR_INDEX_NAME = "chunk_embeddings"

    def __init__(self, session_manager: SessionManager, vector_dimensions: int = 3072):
        """Initialize the VectorRepository.

        Args:
            session_manager: SessionManager instance for database operations.
            vector_dimensions: Embedding vector dimensions (default: 3072 for text-embedding-3-large).
        """
        self._session_manager = session_manager
        self._vector_dimensions = vector_dimensions
        self._apoc_available: Optional[bool] = None  # Cached APOC availability check

    def ensure_index(
        self,
        index_name: Optional[str] = None,
        dimensions: Optional[int] = None,
        similarity: str = "cosine",
    ) -> None:
        """Create vector index for chunk embeddings if it doesn't exist.

        This method is safe to call multiple times - it uses IF NOT EXISTS
        to handle cases where the index already exists.

        Args:
            index_name: Name of the vector index (default: VECTOR_INDEX_NAME).
            dimensions: Embedding dimensions (default: configured vector_dimensions).
            similarity: Similarity function - 'cosine' or 'euclidean' (default: 'cosine').

        Raises:
            ValueError: If similarity function is invalid.
            Neo4jError: If index creation fails.
        """
        index_name = index_name or self.VECTOR_INDEX_NAME
        dimensions = dimensions or self._vector_dimensions

        # Validate similarity function
        valid_similarities = ("cosine", "euclidean")
        if similarity not in valid_similarities:
            raise ValueError(
                f"Invalid similarity function: {similarity}. "
                f"Must be one of: {valid_similarities}"
            )

        # Use the query template from IndexQueries
        query = IndexQueries.CREATE_VECTOR_INDEX.format(
            index_name=index_name,
            dimensions=dimensions,
            similarity=similarity,
        )

        try:
            with self._session_manager.session() as session:
                # Cast to LiteralString for type safety - query is from trusted IndexQueries
                session.run(cast(LiteralString, query))
                logger.info(
                    f"Ensured vector index '{index_name}' exists with "
                    f"dimensions={dimensions}, similarity={similarity}"
                )
        except Neo4jError as e:
            # Handle gracefully - index might already exist with different config
            error_str = str(e).lower()
            if "already exists" in error_str:
                logger.debug(f"Vector index '{index_name}' already exists")
            else:
                logger.warning(f"Vector index creation warning: {e}")
                raise

    def _check_apoc_available(self) -> bool:
        """Check if APOC procedures are available in Neo4j.

        This method checks for APOC availability by attempting to call
        apoc.version(). The result is cached to avoid repeated checks.

        Returns:
            True if APOC is available, False otherwise.

        Note:
            The result is cached after the first check. To force a recheck,
            set self._apoc_available = None before calling.
        """
        # Return cached result if available
        if self._apoc_available is not None:
            return self._apoc_available

        try:
            with self._session_manager.session() as session:
                result = session.run("RETURN apoc.version() AS version")
                record = result.single()
                self._apoc_available = record is not None
                if self._apoc_available and record:
                    logger.debug(f"APOC is available: version {record['version']}")
                return self._apoc_available
        except Neo4jError as e:
            error_str = str(e).lower()
            if any(pattern in error_str for pattern in [
                "unknown function",
                "procedure not found",
                "unknown procedure",
                "no procedure",
            ]):
                logger.warning("APOC is not available in Neo4j")
                self._apoc_available = False
                return False
            # Re-raise unexpected errors
            raise

    def _ensure_apoc_available(self) -> None:
        """Ensure APOC is available, raising an error if not.

        Raises:
            APOCNotAvailableError: If APOC procedures are not available.
        """
        if not self._check_apoc_available():
            raise APOCNotAvailableError(
                "APOC procedures are not available in Neo4j. "
                "APOC is required for unified RAG queries. "
                "Install APOC by following: https://neo4j.com/labs/apoc/"
            )

    def unified_rag_search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 10,
        min_score: float = 0.0,
        include_related_symbols: bool = True,
        include_markdown: bool = True,
    ) -> List[UnifiedRAGResult]:
        """Perform unified vector search with graph context expansion.

        This method executes a single Cypher query that combines:
        1. Vector similarity search on chunk embeddings
        2. File context expansion via CONTAINS relationship
        3. Symbol context expansion via REPRESENTED_BY relationship
        4. Related symbols expansion via CALLS/IMPORTS/USES relationships

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of code results (markdown not counted).
            min_score: Minimum similarity score threshold.
            include_related_symbols: Whether to expand to related symbols.
                Set to False for better performance when related symbols
                are not needed.
            include_markdown: Whether to include markdown documentation chunks.
                When True, markdown chunks are returned separately and don't
                count against top_k. When False, markdown files are excluded.

        Returns:
            List of UnifiedRAGResult with full context, ordered by
            similarity score (descending).

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
            APOCNotAvailableError: When APOC procedures are not available.
            Neo4jError: If the query fails.
        """
        # Ensure APOC is available (required for JSON parsing)
        self._ensure_apoc_available()

        if include_markdown:
            # Execute both code and markdown queries, merge results
            code_results = self._unified_rag_search_code_only(
                query_embedding, repo_id, top_k, min_score, include_related_symbols
            )
            markdown_results = self._unified_rag_search_markdown_only(
                query_embedding, repo_id, min_score
            )
            # Merge results and sort by score descending
            all_results = code_results + markdown_results
            all_results.sort(key=lambda r: r.similarity_score, reverse=True)
            return all_results
        else:
            # Execute code-only query
            return self._unified_rag_search_code_only(
                query_embedding, repo_id, top_k, min_score, include_related_symbols
            )

    def _unified_rag_search_code_only(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int,
        min_score: float,
        include_related_symbols: bool,
    ) -> List[UnifiedRAGResult]:
        """Execute unified RAG search for code files only.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.
            include_related_symbols: Whether to expand to related symbols.

        Returns:
            List of UnifiedRAGResult for code files only.
        """
        # Select appropriate query based on include_related_symbols flag
        if include_related_symbols:
            query = TraversalQueries.UNIFIED_RAG_QUERY_CODE_ONLY
        else:
            query = TraversalQueries.UNIFIED_RAG_QUERY_CODE_ONLY_NO_RELATED

        try:
            with self._session_manager.session() as session:
                result = session.run(
                    query,
                    index_name=self.VECTOR_INDEX_NAME,
                    question_embedding=query_embedding,
                    repo_id=repo_id,
                    top_k=top_k,
                    min_score=min_score,
                )

                return self._parse_unified_rag_results(result)

        except Neo4jError as e:
            self._handle_unified_rag_error(e)
            raise

    def _unified_rag_search_markdown_only(
        self,
        query_embedding: List[float],
        repo_id: str,
        min_score: float,
    ) -> List[UnifiedRAGResult]:
        """Execute unified RAG search for markdown files only.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of UnifiedRAGResult for markdown files only.
        """
        query = TraversalQueries.UNIFIED_RAG_QUERY_MARKDOWN_ONLY

        try:
            with self._session_manager.session() as session:
                result = session.run(
                    query,
                    index_name=self.VECTOR_INDEX_NAME,
                    question_embedding=query_embedding,
                    repo_id=repo_id,
                    markdown_limit=self.MARKDOWN_SEARCH_LIMIT,
                    min_score=min_score,
                )

                return self._parse_unified_rag_results(result)

        except Neo4jError as e:
            self._handle_unified_rag_error(e)
            raise

    def _parse_unified_rag_results(self, result) -> List[UnifiedRAGResult]:
        """Parse Neo4j query results into UnifiedRAGResult objects.

        Args:
            result: Neo4j query result iterator.

        Returns:
            List of UnifiedRAGResult objects.
        """
        results = []
        for record in result:
            # Parse related_symbols - filter out any None entries
            related_symbols = record.get("related_symbols", [])
            if related_symbols is None:
                related_symbols = []
            else:
                # Filter out None entries and ensure proper structure
                related_symbols = [
                    rs for rs in related_symbols
                    if rs is not None and isinstance(rs, dict)
                ]

            # Determine if this is a documentation chunk
            file_path = record.get("file_path", "")
            # Use is_documentation from query if available, otherwise infer from file_path
            is_documentation = record.get("is_documentation")
            if is_documentation is None:
                is_documentation = (
                    file_path is not None and
                    file_path.endswith(".md")
                )

            results.append(UnifiedRAGResult(
                chunk_id=record["chunk_id"],
                chunk_content=record["chunk_content"],
                start_line=record["start_line"],
                end_line=record["end_line"],
                similarity_score=record["similarity_score"],
                file_path=file_path or "",
                symbol_name=record.get("symbol_name"),
                symbol_kind=record.get("symbol_kind"),
                related_symbols=related_symbols,
                is_documentation=is_documentation,
            ))

        return results

    def _handle_unified_rag_error(self, e: Neo4jError) -> None:
        """Handle Neo4j unified RAG search errors.

        Args:
            e: The Neo4jError that occurred.

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
            APOCNotAvailableError: When APOC procedures are not available.
        """
        error_str = str(e).lower()
        # Check for vector index not available errors
        if any(pattern in error_str for pattern in [
            "no such index",
            "index does not exist",
            "unknown index",
            "there is no such index",
            "index not found",
        ]):
            logger.warning(
                f"Vector index '{self.VECTOR_INDEX_NAME}' is not available: {e}"
            )
            raise VectorIndexNotAvailableError(
                f"Vector index '{self.VECTOR_INDEX_NAME}' is not available. "
                f"Ensure the index exists and is ONLINE. Original error: {e}"
            ) from e
        # Check for APOC not available errors
        if any(pattern in error_str for pattern in [
            "unknown function",
            "procedure not found",
            "unknown procedure",
            "no procedure",
            "apoc",
        ]):
            logger.warning(f"APOC procedure error: {e}")
            # Reset cached value since it might have changed
            self._apoc_available = None
            raise APOCNotAvailableError(
                f"APOC procedures are not available or failed. "
                f"Original error: {e}"
            ) from e
        logger.error(f"Unified RAG search failed: {e}")

    # Default limit for markdown chunks (high value to get all relevant docs)
    MARKDOWN_SEARCH_LIMIT = 100

    def search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 500,
        min_score: float = 0.0,
        include_markdown: bool = True,
    ) -> List[VectorSearchResult]:
        """Search for similar chunks using Neo4j vector index.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of code results (markdown not counted).
            min_score: Minimum similarity score threshold.
            include_markdown: Whether to include markdown documentation chunks.
                When True, markdown chunks are returned separately and don't
                count against top_k. When False, markdown files are excluded.

        Returns:
            List of VectorSearchResult ordered by similarity (descending).
            Code chunks are limited to top_k, markdown chunks are unlimited
            (subject only to min_score threshold).

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
            Neo4jError: If search fails.
        """
        if include_markdown:
            # Execute both code and markdown queries, merge results
            code_results = self._search_code_only(
                query_embedding, repo_id, top_k, min_score
            )
            markdown_results = self._search_markdown_only(
                query_embedding, repo_id, min_score
            )
            # Merge results: code first (by score), then markdown (by score)
            all_results = code_results + markdown_results
            # Sort all by score descending
            all_results.sort(key=lambda r: r.score, reverse=True)
            return all_results
        else:
            # Execute code-only query
            return self._search_code_only(
                query_embedding, repo_id, top_k, min_score
            )

    def _search_code_only(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int,
        min_score: float,
    ) -> List[VectorSearchResult]:
        """Search for similar code chunks (excludes markdown).

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            top_k: Maximum number of results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of VectorSearchResult for code files only.
        """
        query = VectorQueries.VECTOR_SEARCH_CODE_ONLY.format(
            index_name=self.VECTOR_INDEX_NAME
        )

        try:
            with self._session_manager.session() as session:
                result = session.run(
                    query,
                    embedding=query_embedding,
                    repo_id=repo_id,
                    top_k=top_k,
                    min_score=min_score,
                )

                return self._parse_search_results(result, is_documentation=False)

        except Neo4jError as e:
            self._handle_search_error(e)
            raise  # Re-raise if not handled

    def _search_markdown_only(
        self,
        query_embedding: List[float],
        repo_id: str,
        min_score: float,
    ) -> List[VectorSearchResult]:
        """Search for similar markdown documentation chunks.

        Args:
            query_embedding: Query vector embedding.
            repo_id: Repository ID to filter results.
            min_score: Minimum similarity score threshold.

        Returns:
            List of VectorSearchResult for markdown files only.
        """
        query = VectorQueries.VECTOR_SEARCH_MARKDOWN_ONLY.format(
            index_name=self.VECTOR_INDEX_NAME
        )

        try:
            with self._session_manager.session() as session:
                result = session.run(
                    query,
                    embedding=query_embedding,
                    repo_id=repo_id,
                    markdown_limit=self.MARKDOWN_SEARCH_LIMIT,
                    min_score=min_score,
                )

                return self._parse_search_results(result, is_documentation=True)

        except Neo4jError as e:
            self._handle_search_error(e)
            raise  # Re-raise if not handled

    def _parse_search_results(
        self,
        result,
        is_documentation: bool = False,
    ) -> List[VectorSearchResult]:
        """Parse Neo4j query results into VectorSearchResult objects.

        Args:
            result: Neo4j query result iterator.
            is_documentation: Whether these results are from markdown files.

        Returns:
            List of VectorSearchResult objects.
        """
        results = []
        for record in result:
            node_data = record["node"]
            score = record["score"]

            # Use is_documentation from query if available, otherwise use parameter
            is_doc = record.get("is_documentation", is_documentation)

            # Extract required properties
            file_path = node_data.get("file_path")
            start_line = node_data.get("start_line")
            end_line = node_data.get("end_line")

            # Handle symbols_defined/referenced - may be list or CSV string
            symbols_defined = self._parse_symbols_list(
                node_data.get("symbols_defined", [])
            )
            symbols_referenced = self._parse_symbols_list(
                node_data.get("symbols_referenced", [])
            )

            results.append(VectorSearchResult(
                node_id=node_data.get("id", ""),
                score=score,
                node=GraphNode(
                    id=node_data.get("id", ""),
                    type=GraphNodeType.CHUNK,
                    repo_id=node_data.get("repo_id", ""),
                    attrs={
                        "file_path": file_path,
                        "start_line": start_line,
                        "end_line": end_line,
                        "language": node_data.get("language"),
                        "symbols_defined": symbols_defined,
                        "symbols_referenced": symbols_referenced,
                    },
                    summary=None,
                ),
                content=node_data.get("content"),
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                is_documentation=is_doc,
            ))

        return results

    def _handle_search_error(self, e: Neo4jError) -> None:
        """Handle Neo4j search errors, raising appropriate exceptions.

        Args:
            e: The Neo4jError that occurred.

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
        """
        error_str = str(e).lower()
        # Check for vector index not available errors
        if any(pattern in error_str for pattern in [
            "no such index",
            "index does not exist",
            "unknown index",
            "there is no such index",
            "index not found",
            "procedure not found",
            "unknown procedure",
        ]):
            logger.warning(
                f"Vector index '{self.VECTOR_INDEX_NAME}' is not available: {e}"
            )
            raise VectorIndexNotAvailableError(
                f"Vector index '{self.VECTOR_INDEX_NAME}' is not available. "
                f"Ensure the index exists and is ONLINE. Original error: {e}"
            ) from e
        logger.error(f"Vector search failed: {e}")


    def hybrid_search(
        self,
        query_embedding: List[float],
        repo_id: str,
        top_k: int = 200,
        expand_graph: bool = True,
        expansion_hops: int = 10,
        max_expand: Optional[int] = None,
        max_expansion_nodes: int = 500,
        edge_types: Optional[List[str]] = None,
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
                Defaults to top_k (expand all results). Set to a lower value
                to limit graph expansion for performance.
            max_expansion_nodes: Maximum number of nodes to return per symbol expansion.
                Defaults to 100 to prevent explosion.
            edge_types: List of edge types to use for graph expansion.
                If None, uses semantic edges as fallback.

        Returns:
            Tuple of (vector_results, graph_expanded_nodes).

        Raises:
            VectorIndexNotAvailableError: When the vector index is not available.
            Neo4jError: If search fails.
        """
        # Step 1: Vector search
        vector_results = self.search(query_embedding, repo_id, top_k)

        if not expand_graph or not vector_results:
            return vector_results, []

        # Step 2: Extract symbols from vector results and expand via graph
        expanded_nodes: List[GraphNode] = []
        seen_ids = {r.node_id for r in vector_results}

        # Determine how many results to expand
        if max_expand is None:
            max_expand = top_k  # Expand all vector results by default
        else:
            max_expand = min(max_expand, top_k, len(vector_results))

        symbols_found_count = 0
        for result in vector_results[:max_expand]:
            symbols = result.node.attrs.get("symbols_defined", [])
            if isinstance(symbols, str):
                symbols = [s.strip() for s in symbols.split(",") if s.strip()]

            logger.debug(f"Processing vector result: {result.node.id}, symbols: {symbols}")
            symbols_found_count += len(symbols)
            for symbol_name in symbols:
                # Find symbol node and its neighbors
                neighbors = self._expand_from_symbol(
                    repo_id, symbol_name, expansion_hops, seen_ids, max_expansion_nodes, edge_types
                )
                logger.debug(f"Symbol '{symbol_name}' expanded to {len(neighbors)} neighbors")
                expanded_nodes.extend(neighbors)
                seen_ids.update(n.id for n in neighbors)

        logger.debug(
            f"Graph expansion: {len(vector_results)} vector results, "
            f"{symbols_found_count} symbols extracted, "
            f"{len(expanded_nodes)} expanded nodes found"
        )

        return vector_results, expanded_nodes

    def _expand_from_symbol(
        self,
        repo_id: str,
        symbol_name: str,
        hops: int,
        exclude_ids: set,
        limit: int,
        edge_types: Optional[List[str]] = None,
    ) -> List[GraphNode]:
        """Expand from a symbol to find related chunks via graph.

        Args:
            repo_id: Repository ID.
            symbol_name: Symbol name to expand from.
            hops: Number of hops to traverse.
            exclude_ids: Node IDs to exclude from results.
            limit: Maximum number of nodes to return.
            edge_types: List of edge types to use. If None, uses semantic edges as fallback.

        Returns:
            List of related GraphNode objects.
        """
        # Use provided edge types or fallback to semantic edges
        if edge_types is None:
            edge_types = GraphEdgeType.semantic_edges()

        # Use the query from EdgeQueries with hops baked in
        query = EdgeQueries.get_expand_from_symbol_query(hops=hops, edge_types=edge_types)

        try:
            with self._session_manager.session() as session:
                # Try multiple symbol pattern formats to handle different JSON structures
                symbol_patterns = [
                    f'"name": "{symbol_name}"',  # Standard JSON format
                    f'"name":"{symbol_name}"',   # No spaces
                    f'name": "{symbol_name}"',   # Missing opening quote
                    f'"name" : "{symbol_name}"', # Extra spaces
                    symbol_name,                 # Just the name itself
                ]

                all_results = []
                for pattern in symbol_patterns:
                    # Cast to LiteralString for type safety - query is from trusted EdgeQueries
                    result = session.run(
                        cast(LiteralString, query),
                        repo_id=repo_id,
                        symbol_pattern=pattern,
                        exclude_ids=list(exclude_ids),
                        limit=limit,
                    )
                    results = [self._record_to_node(record) for record in result]
                    all_results.extend(results)

                    # If we found results with this pattern, use them
                    if results:
                        logger.debug(f"Symbol expansion found {len(results)} nodes for {symbol_name} with pattern: {pattern}")
                        return results[:limit]  # Return first successful match, limited

                # If no pattern worked, try a broader search using symbol name directly
                if not all_results:
                    result = session.run(
                        TraversalQueries.build_symbol_expansion_query(edge_pattern, hops),
                        repo_id=repo_id,
                        symbol_name=symbol_name,
                        exclude_ids=list(exclude_ids),
                        limit=limit,
                    )
                    results = [self._record_to_node(record) for record in result]
                    if results:
                        logger.debug(f"Broader symbol search found {len(results)} nodes for {symbol_name}")
                        return results

                logger.debug(f"No symbol expansion results found for {symbol_name}")
                return []

        except Neo4jError as e:
            logger.debug(f"Symbol expansion failed for {symbol_name}: {e}")
            return []

    def _record_to_node(self, record) -> GraphNode:
        """Convert a Neo4j record to a GraphNode.

        Args:
            record: Neo4j record with 'node' and 'labels' fields.

        Returns:
            GraphNode instance.
        """
        node_data = record["node"]
        labels = record.get("labels", ["Chunk"])

        # Determine node type from labels
        node_type = GraphNodeType.CHUNK  # Default for vector search results
        for label in labels:
            try:
                node_type = GraphNodeType(label)
                break
            except ValueError:
                continue

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
        else:
            attrs = self._deserialize_attrs(node_data.get("attrs", "{}"))

        return GraphNode(
            id=node_data.get("id", ""),
            type=node_type,
            repo_id=node_data.get("repo_id", ""),
            attrs=attrs,
            summary=node_data.get("summary"),
        )

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

    def _deserialize_attrs(self, attrs_str: Optional[str]) -> Dict[str, Any]:
        """Deserialize attributes from JSON string.

        Args:
            attrs_str: JSON string of attributes.

        Returns:
            Dictionary of attributes.
        """
        import json
        if not attrs_str:
            return {}
        try:
            return json.loads(attrs_str)
        except (json.JSONDecodeError, TypeError):
            return {}
