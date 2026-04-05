"""Code Retrieval Service for hybrid vector + graph search.

This service consolidates GraphRAGService and Retriever functionality,
providing hybrid retrieval combining vector search with graph traversal.
It accesses storage only through adapters.
"""

import os
import re
from typing import Any, Callable, List, Optional, Set, Tuple

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..adapters.storage import SymbolQueryAdapter, TraversalAdapter
from ..analysis.builders.context_packet import (
    ContextPacketBuilderV2 as ContextPacketBuilder,
)
from ..analysis.builders.subgraph_visualizer import (
    SubgraphVisualizerV2 as SubgraphVisualizer,
)
from ..models.base import (
    Anchors,
    ContextItem,
    GraphNode,
    RetrievalResponse,
)
from ..models.enums import ContextItemType, GraphEdgeType
from ..models.retrieval import CandidateChunk, RetrievalConfig, RetrievalStep
from ..models.visualization import VisEdge, VisGraph, VisNode
from ..processing.embedding_generator import (
    EmbeddingGenerator as BaseEmbeddingGenerator,
)
from ..querying.models import (
    ContextPacket,
    GraphRAGResult,
    TraversalResult,
)
from ..storage.vector_store import ChromaVectorStore, SearchResult

logger = EnhancedLogger(__name__)


class CodeRetrievalService:
    """Service for semantic code search and context building.

    **Purpose**: Find relevant code using natural language queries and build
    comprehensive context through hybrid vector + graph search.

    **Use this service when**:
    - User asks natural language questions ("How does authentication work?")
    - You need to find relevant code without knowing exact symbol names
    - You want ranked results by relevance (semantic similarity + graph proximity)
    - You're building RAG (Retrieval Augmented Generation) features
    - You need comprehensive context for code understanding or debugging

    **Key capabilities**:
    - Semantic search using embeddings (understands query meaning)
    - Hybrid retrieval: vector similarity + graph relationships
    - Intelligent ranking: combines vector scores, graph distance, location bonuses
    - Context building: assembles comprehensive context packets
    - Token-aware pruning: fits results within token limits
    - Anchor expansion: uses current file and error stacks for focused retrieval

    **Contrast with CodeQueryService**:
    - CodeQueryService: Exact lookups, graph traversal, no ranking
    - CodeRetrievalService: Semantic search, natural language queries, ranked results

    **Example**:
        >>> # Natural language query - finds relevant code semantically
        >>> result = service.retrieve_context(
        ...     repo_id="my-repo",
        ...     query="How does user authentication work?",
        ...     max_depth=5
        ... )
        >>> # Returns: context packets with auth-related symbols, relationships,
        >>> # and visualization of how they connect
        >>>
        >>> # Hybrid search with anchors (current file + error context)
        >>> response = service.retrieve(
        ...     repo_id="my-repo",
        ...     query="payment processing error",
        ...     anchors=Anchors(
        ...         current_file="src/payments/gateway.py",
        ...         error_stack=traceback_string
        ...     )
        ... )

    **Pipeline**: Query → Symbol Identification (vector + pattern + graph) →
                 Graph Expansion → Ranking → Pruning → Context Packets
    """

    def __init__(
        self,
        symbol_adapter: SymbolQueryAdapter,
        traversal_adapter: TraversalAdapter,
        vector_store: ChromaVectorStore,
        embedding_generator: BaseEmbeddingGenerator,
        config: Optional[RetrievalConfig] = None,
    ):
        """Initialize the CodeRetrievalService.

        Args:
            symbol_adapter: Adapter for symbol query operations.
            traversal_adapter: Adapter for graph traversal operations.
            vector_store: ChromaDB vector store for semantic search.
            embedding_generator: Generator for query embeddings.
            config: Optional retrieval configuration.
        """
        self._symbol_adapter = symbol_adapter
        self._traversal_adapter = traversal_adapter
        self._vector_store = vector_store
        self._embedding_generator = embedding_generator
        self._config = config or RetrievalConfig()

        # Initialize builders for Graph RAG functionality
        self._packet_builder = ContextPacketBuilder()
        self._visualizer = SubgraphVisualizer()

    # =========================================================================
    # Main Retrieval Methods
    # =========================================================================

    def retrieve(
        self,
        repo_id: str,
        query: str,
        anchors: Optional[Anchors] = None,
        max_tokens: Optional[int] = None,
        config: Optional[RetrievalConfig] = None,
    ) -> RetrievalResponse:
        """Retrieve relevant code context using hybrid approach.

        Combines vector search, anchor expansion, and graph expansion.

        Args:
            repo_id: The repository ID to search.
            query: The search query.
            anchors: Optional contextual anchors for focused retrieval.
            max_tokens: Optional override for max context tokens.
            config: Optional RetrievalConfig to override instance config.

        Returns:
            RetrievalResponse containing context items.
        """
        effective_config = config or self._config
        max_tokens = max_tokens or effective_config.max_context_tokens

        # Check for domain-level query
        domain_name = self._detect_domain_query(query)
        if domain_name:
            return self._retrieve_domain(repo_id, domain_name, query, max_tokens, effective_config)

        # Standard retrieval flow
        # Step 1: Vector search
        candidates = self._vector_search(repo_id, query, effective_config)

        # Step 2: Anchor expansion
        if anchors:
            anchor_candidates = self._expand_from_anchors(repo_id, anchors, effective_config)
            candidates = self._merge_candidates(candidates, anchor_candidates)

        # Step 3: Graph expansion
        candidates = self._expand_via_graph(repo_id, candidates, effective_config)

        # Step 4: Location bonuses
        if anchors and anchors.current_file:
            candidates = self._apply_location_bonuses(candidates, anchors.current_file, effective_config)

        # Step 5: Rank and prune
        ranked_candidates = self._rank_candidates(candidates, effective_config)
        pruned_candidates = self._prune_to_token_limit(ranked_candidates, max_tokens)

        # Step 6: Build response
        context_items = self._build_context_items(pruned_candidates)

        # Step 7: Add graph paths if relevant
        if anchors and anchors.current_file:
            graph_paths = self._find_graph_paths(repo_id, anchors, pruned_candidates)
            context_items.extend(graph_paths)

        return RetrievalResponse(context_items=context_items)

    async def retrieve_with_progress(
        self,
        repo_id: str,
        query: str,
        anchors: Optional[Anchors] = None,
        max_tokens: Optional[int] = None,
        progress_callback: Optional[Callable[[str, int, int], Any]] = None,
        config: Optional[RetrievalConfig] = None,
    ) -> RetrievalResponse:
        """Retrieve relevant code context with progress updates.

        This is the async version of retrieve() that provides progress callbacks
        for UI updates during the retrieval process.

        Args:
            repo_id: The repository ID to search.
            query: The search query.
            anchors: Optional contextual anchors for focused retrieval.
            max_tokens: Optional override for max context tokens.
            progress_callback: Optional async callback(step_name, current, total) for progress updates.
            config: Optional RetrievalConfig to override instance config.

        Returns:
            RetrievalResponse containing context items.
        """
        import asyncio

        effective_config = config or self._config
        max_tokens = max_tokens or effective_config.max_context_tokens

        async def report_progress(step: str, current: int, total: int):
            if progress_callback:
                logger.info(
                    f"Retrieval progress: {step}",
                    data={'step': step, 'current': current, 'total': total, 'repo_id': repo_id}
                )
                result = progress_callback(step, current, total)
                # Handle both sync and async callbacks
                if asyncio.iscoroutine(result):
                    await result

        # Check for domain-level query
        domain_name = self._detect_domain_query(query)
        if domain_name:
            await report_progress(RetrievalStep.DOMAIN_RETRIEVAL, 1, 1)
            return self._retrieve_domain(repo_id, domain_name, query, max_tokens, effective_config)

        # Step 1: Vector search for semantic similarity
        await report_progress(RetrievalStep.VECTOR_SEARCH, 1, 6)
        logger.info("Starting vector search", data={'repo_id': repo_id, 'query_length': len(query)})
        candidates = self._vector_search(repo_id, query, effective_config)
        logger.info(
            "Vector search completed",
            data={'repo_id': repo_id, 'candidates_found': len(candidates)}
        )

        # Step 2: Anchor-based expansion
        await report_progress(RetrievalStep.ANCHOR_EXPANSION, 2, 6)
        if anchors:
            logger.info("Starting anchor expansion", data={'repo_id': repo_id, 'has_current_file': bool(anchors.current_file)})
            anchor_candidates = self._expand_from_anchors(repo_id, anchors, effective_config)
            candidates = self._merge_candidates(candidates, anchor_candidates)
            logger.info(
                "Anchor expansion completed",
                data={'repo_id': repo_id, 'total_candidates': len(candidates)}
            )

        # Step 3: Graph expansion
        await report_progress(RetrievalStep.GRAPH_EXPANSION, 3, 6)
        logger.info(
            "Starting graph expansion",
            data={
                'repo_id': repo_id,
                'initial_candidates': len(candidates),
                'expansion_hops': effective_config.graph_expansion_hops
            }
        )
        candidates = self._expand_via_graph(repo_id, candidates, effective_config)
        logger.info(
            "Graph expansion completed",
            data={
                'repo_id': repo_id,
                'total_candidates': len(candidates),
                'nodes_explored': len(candidates)  # Track nodes explored
            }
        )

        # Step 4: Apply file/directory bonuses
        await report_progress(RetrievalStep.LOCATION_SCORING, 4, 6)
        if anchors and anchors.current_file:
            logger.info("Starting location scoring", data={'repo_id': repo_id, 'anchor_file': anchors.current_file})
            candidates = self._apply_location_bonuses(candidates, anchors.current_file, effective_config)
            logger.info("Location scoring completed", data={'repo_id': repo_id})

        # Step 5: Rank candidates
        await report_progress(RetrievalStep.RANKING_RESULTS, 5, 6)
        logger.info(
            "Starting ranking",
            data={'repo_id': repo_id, 'candidates_to_rank': len(candidates)}
        )
        ranked_candidates = self._rank_candidates(candidates, effective_config)
        logger.info(
            "Ranking completed",
            data={'repo_id': repo_id, 'ranked_candidates': len(ranked_candidates)}
        )

        # Step 6: Prune to token limit and build response
        await report_progress(RetrievalStep.BUILDING_CONTEXT, 6, 6)
        logger.info(
            "Starting context building",
            data={'repo_id': repo_id, 'max_tokens': max_tokens}
        )
        pruned_candidates = self._prune_to_token_limit(ranked_candidates, max_tokens)
        context_items = self._build_context_items(pruned_candidates)
        logger.info(
            "Context building completed",
            data={
                'repo_id': repo_id,
                'pruned_candidates': len(pruned_candidates),
                'context_items': len(context_items)
            }
        )

        # Add graph paths if relevant
        if anchors and anchors.current_file:
            graph_paths = self._find_graph_paths(repo_id, anchors, pruned_candidates)
            context_items.extend(graph_paths)

        return RetrievalResponse(context_items=context_items)

    def retrieve_context(
        self,
        repo_id: str,
        query: str,
        max_depth: int = 5,
        include_visualization: bool = True,
        config: Optional[RetrievalConfig] = None,
    ) -> GraphRAGResult:
        """Retrieve context using Graph RAG pipeline.

        Pipeline: Query → Symbol Identification → Graph Expansion → Context Packets

        Args:
            repo_id: The repository ID to search.
            query: The user's query string.
            max_depth: Maximum traversal depth.
            include_visualization: Whether to generate visualization.
            config: Optional RetrievalConfig to override instance config.

        Returns:
            GraphRAGResult containing context packets and visualization.
        """
        effective_config = config or self._config
        # Clamp max_depth
        from graph_kb_api.config import settings
        max_depth = max(1, min(max_depth, settings.max_depth))

        # Step 1: Identify starting symbols (pass config to use top_k_vector)
        symbol_ids = self._identify_starting_symbols(repo_id, query, effective_config)

        if not symbol_ids:
            logger.info("No starting symbols found for query: %s", query)
            return GraphRAGResult(
                query=query,
                context_packets=[],
                visualization=None,
                symbols_found=[],
                total_nodes_explored=0,
                retrieval_strategy="graph_first",
            )

        # Step 2: Expand and build packets
        packets, all_nodes, all_edges = self._expand_and_build_packets(
            repo_id=repo_id,
            symbol_ids=symbol_ids,
            max_depth=max_depth,
        )

        # Step 3: Generate visualization
        visualization = None
        vis_graph = None

        if include_visualization and all_nodes:
            combined_result = TraversalResult(
                nodes=all_nodes,
                edges=all_edges,
                depth_reached=max_depth,
                is_truncated=False,
                node_count_by_depth={},
            )
            visualization = self._visualizer.generate_diagram(combined_result)
            vis_graph = self._build_vis_graph(all_nodes, all_edges)

        return GraphRAGResult(
            query=query,
            context_packets=packets,
            visualization=visualization,
            symbols_found=symbol_ids,
            total_nodes_explored=len(all_nodes),
            retrieval_strategy="graph_first",
            vis_graph=vis_graph,
        )

    def retrieve_for_symbol(
        self,
        symbol_id: str,
        max_depth: int = 5,
        include_visualization: bool = True,
        config: Optional[RetrievalConfig] = None,
    ) -> GraphRAGResult:
        """Retrieve context for a specific symbol.

        Args:
            symbol_id: The symbol ID to start from.
            max_depth: Maximum traversal depth.
            include_visualization: Whether to generate visualization.
            config: Optional RetrievalConfig to override instance config.

        Returns:
            GraphRAGResult containing context packets and visualization.
        """
        max_depth = max(1, min(max_depth, 10))

        # Get bidirectional neighborhood
        result = self._traversal_adapter.get_bidirectional_neighborhood(
            node_id=symbol_id,
            max_depth=max_depth,
        )

        if not result.nodes:
            return GraphRAGResult(
                query=symbol_id,
                context_packets=[],
                visualization=None,
                symbols_found=[symbol_id],
                total_nodes_explored=0,
                retrieval_strategy="graph_first",
            )

        # Build context packet
        packet = self._packet_builder.build_packet(
            traversal_result=result,
            root_symbol=symbol_id,
        )

        # Generate visualization
        visualization = None
        if include_visualization:
            visualization = self._visualizer.generate_diagram(result)

        return GraphRAGResult(
            query=symbol_id,
            context_packets=[packet],
            visualization=visualization,
            symbols_found=[symbol_id],
            total_nodes_explored=len(result.nodes),
            retrieval_strategy="graph_first",
        )

    # =========================================================================
    # Internal Methods - Vector Search
    # =========================================================================

    def _vector_search(
        self, repo_id: str, query: str, config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Perform vector search for semantic similarity."""
        effective_config = config or self._config
        query_embedding = self._embedding_generator.embed(query)

        results = self._vector_store.search(
            query_embedding=query_embedding,
            repo_id=repo_id,
            top_k=effective_config.top_k_vector,
        )

        candidates = []
        for result in results:
            candidate = self._search_result_to_candidate(result)
            if candidate:
                candidates.append(candidate)

        return candidates

    def _search_result_to_candidate(
        self, result: SearchResult
    ) -> Optional[CandidateChunk]:
        """Convert search result to candidate chunk."""
        metadata = result.metadata
        if not metadata:
            return None

        symbols_defined = metadata.get("symbols_defined", "")
        symbol = symbols_defined.split(",")[0] if symbols_defined else None

        return CandidateChunk(
            chunk_id=result.chunk_id,
            file_path=metadata.get("file_path", ""),
            start_line=int(metadata.get("start_line", 0)),
            end_line=int(metadata.get("end_line", 0)),
            content=result.content or "",
            symbol=symbol,
            vector_score=result.score,
            metadata=metadata,
        )

    # =========================================================================
    # Internal Methods - Anchor Expansion
    # =========================================================================

    def _expand_from_anchors(
        self, repo_id: str, anchors: Anchors, config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Expand candidates from anchor information."""
        candidates = []

        if anchors.current_file:
            file_candidates = self._get_chunks_for_file(repo_id, anchors.current_file, config)
            for candidate in file_candidates:
                candidate.is_anchor = True
            candidates.extend(file_candidates)

        if anchors.error_stack:
            stack_candidates = self._parse_error_stack(repo_id, anchors.error_stack, config)
            for candidate in stack_candidates:
                candidate.is_anchor = True
            candidates.extend(stack_candidates)

        return candidates

    def _get_chunks_for_file(
        self, repo_id: str, file_path: str, config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Get all chunks for a specific file."""
        effective_config = config or self._config
        try:
            zero_embedding = [0.0] * self._embedding_generator.dimensions
            # Use configured top_k (capped at reasonable max for single file)
            file_top_k = min(effective_config.top_k_vector, 500)

            results = self._vector_store.search(
                query_embedding=zero_embedding,
                repo_id=repo_id,
                top_k=file_top_k,
                filter_metadata={"file_path": file_path},
            )

            candidates = []
            for result in results:
                candidate = self._search_result_to_candidate(result)
                if candidate:
                    candidate.vector_score = 0.5
                    candidates.append(candidate)

            return candidates
        except Exception as e:
            logger.warning(f"Failed to get chunks for file {file_path}: {e}")
            return []

    def _parse_error_stack(
        self, repo_id: str, error_stack: str, config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Parse error stack trace and get relevant chunks."""
        candidates = []
        patterns = [
            r'File "([^"]+)", line (\d+)',
            r'at\s+(?:\S+\s+\()?([^:]+):(\d+)',
            r'([^\s:]+):(\d+)',
        ]

        seen_files: Set[str] = set()

        for pattern in patterns:
            matches = re.findall(pattern, error_stack)
            for match in matches:
                file_path = match[0]
                line_number = int(match[1])

                if file_path in seen_files:
                    continue
                seen_files.add(file_path)

                file_candidates = self._get_chunks_for_file(repo_id, file_path, config)

                for candidate in file_candidates:
                    if candidate.start_line <= line_number <= candidate.end_line:
                        candidate.vector_score = 0.7
                        candidates.append(candidate)
                        break
                else:
                    candidates.extend(file_candidates[:3])

        return candidates

    # =========================================================================
    # Internal Methods - Graph Expansion
    # =========================================================================

    def _expand_via_graph(
        self, repo_id: str, candidates: List[CandidateChunk], config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Expand candidates by traversing graph relationships."""
        effective_config = config or self._config
        expanded = list(candidates)
        seen_chunk_ids: Set[str] = {c.chunk_id for c in candidates}

        # Get symbols from current candidates
        symbols_to_expand: Set[str] = set()
        for candidate in candidates:
            if candidate.symbol:
                symbols_to_expand.add(candidate.symbol)
            symbols_str = candidate.metadata.get("symbols_defined", "")
            if symbols_str:
                symbols_to_expand.update(symbols_str.split(","))

        logger.info(
            f"Graph expansion: starting with {len(symbols_to_expand)} symbols",
            data={
                'repo_id': repo_id,
                'symbols_count': len(symbols_to_expand),
                'max_depth': effective_config.graph_expansion_hops
            }
        )

        # Track statistics
        total_nodes_explored = 0
        successful_expansions = 0
        failed_expansions = 0

        # Use traversal adapter for multi-hop expansion (edge types handled by adapter)
        for symbol_id in symbols_to_expand:
            try:
                result = self._traversal_adapter.get_reachable_subgraph(
                    start_id=symbol_id,
                    max_depth=effective_config.graph_expansion_hops,
                    allowed_edges=None,  # Let adapter determine appropriate edges
                    direction="both",
                )

                for node in result.nodes:
                    if node.id == symbol_id:
                        continue

                    chunk = self._node_to_candidate_chunk(node, result.depth_reached)
                    if chunk and chunk.chunk_id not in seen_chunk_ids:
                        expanded.append(chunk)
                        seen_chunk_ids.add(chunk.chunk_id)

            except Exception as e:
                logger.debug(f"Failed to expand symbol {symbol_id}: {e}")

        logger.info(
            "Graph expansion complete",
            data={
                'repo_id': repo_id,
                'symbols_expanded': len(symbols_to_expand),
                'successful_expansions': successful_expansions,
                'failed_expansions': failed_expansions,
                'total_nodes_explored': total_nodes_explored,
                'initial_candidates': len(candidates),
                'final_candidates': len(expanded),
                'new_candidates_added': len(expanded) - len(candidates)
            }
        )

        return expanded

    def _node_to_candidate_chunk(
        self, node: GraphNode, depth: int
    ) -> Optional[CandidateChunk]:
        """Convert GraphNode to CandidateChunk."""
        attrs = node.attrs or {}

        file_path = attrs.get("file_path", "")
        start_line = attrs.get("start_line", 0)
        end_line = attrs.get("end_line", 0)
        name = attrs.get("name", "")
        docstring = attrs.get("docstring", "")

        content = node.summary or docstring or ""

        if not file_path and not content:
            return None

        return CandidateChunk(
            chunk_id=node.id,
            file_path=file_path,
            start_line=int(start_line) if start_line else 0,
            end_line=int(end_line) if end_line else 0,
            content=content,
            symbol=name or None,
            vector_score=0.0,
            graph_distance=depth,
            metadata=attrs,
        )

    # =========================================================================
    # Internal Methods - Ranking and Pruning
    # =========================================================================

    def _apply_location_bonuses(
        self, candidates: List[CandidateChunk], current_file: str, config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Apply same-file and same-directory bonuses."""
        effective_config = config or self._config
        current_dir = os.path.dirname(current_file)

        for candidate in candidates:
            if candidate.file_path == current_file:
                candidate.vector_score += effective_config.same_file_bonus
            elif os.path.dirname(candidate.file_path) == current_dir:
                candidate.vector_score += effective_config.same_directory_bonus

        return candidates

    def _merge_candidates(
        self,
        primary: List[CandidateChunk],
        secondary: List[CandidateChunk],
    ) -> List[CandidateChunk]:
        """Merge two lists of candidates, avoiding duplicates."""
        seen_ids: Set[str] = {c.chunk_id for c in primary}
        merged = list(primary)

        for candidate in secondary:
            if candidate.chunk_id not in seen_ids:
                merged.append(candidate)
                seen_ids.add(candidate.chunk_id)

        return merged

    def _rank_candidates(
        self, candidates: List[CandidateChunk], config: Optional[RetrievalConfig] = None
    ) -> List[CandidateChunk]:
        """Rank candidates by final score.

        Args:
            candidates: List of candidate chunks to rank.
            config: Optional RetrievalConfig. If None, uses instance config.

        Returns:
            Ranked list of candidates (sorted by final_score descending),
            or original order if ranking is disabled.
        """
        effective_config = config or self._config

        # If ranking is disabled, return candidates in original order
        if not effective_config.enable_ranking:
            return candidates

        return sorted(candidates, key=lambda c: c.final_score, reverse=True)

    def _prune_to_token_limit(
        self, candidates: List[CandidateChunk], max_tokens: int
    ) -> List[CandidateChunk]:
        """Prune candidates to fit within token limit."""
        pruned = []
        total_tokens = 0

        for candidate in candidates:
            chunk_tokens = self._estimate_tokens(candidate)

            if total_tokens + chunk_tokens <= max_tokens:
                pruned.append(candidate)
                total_tokens += chunk_tokens
            elif not pruned:
                pruned.append(candidate)
                break

        return pruned

    def _estimate_tokens(self, candidate: CandidateChunk) -> int:
        """Estimate token count for a candidate chunk."""
        if candidate.content:
            return len(candidate.content) // 4

        line_count = candidate.end_line - candidate.start_line + 1
        return int(line_count * self._config.tokens_per_line)

    def _build_context_items(
        self, candidates: List[CandidateChunk]
    ) -> List[ContextItem]:
        """Build context items from candidates."""
        items = []

        for candidate in candidates:
            item = ContextItem(
                type=ContextItemType.CHUNK,
                file_path=candidate.file_path,
                start_line=candidate.start_line,
                end_line=candidate.end_line,
                content=candidate.content,
                symbol=candidate.symbol,
                score=candidate.final_score,
            )
            items.append(item)

        return items

    def _find_graph_paths(
        self,
        repo_id: str,
        anchors: Anchors,
        candidates: List[CandidateChunk],
    ) -> List[ContextItem]:
        """Find relevant graph paths between anchors and candidates."""
        # Simplified implementation - would need access to graph_store
        # TODO: Add path finding through adapter
        return []

    # =========================================================================
    # Internal Methods - Symbol Identification (Graph RAG)
    # =========================================================================

    def _identify_starting_symbols(
        self, repo_id: str, query: str, config: Optional[RetrievalConfig] = None
    ) -> List[str]:
        """Identify candidate starting symbols from query."""
        effective_config = config or self._config
        symbol_ids: List[str] = []
        seen_ids: Set[str] = set()

        # Strategy 1: Vector search
        vector_symbols = self._identify_via_vector_search(repo_id, query, effective_config)
        for sid in vector_symbols:
            if sid not in seen_ids:
                symbol_ids.append(sid)
                seen_ids.add(sid)

        # Strategy 2: Pattern matching
        pattern_symbols = self._identify_via_pattern_matching(repo_id, query)
        for sid in pattern_symbols:
            if sid not in seen_ids:
                symbol_ids.append(sid)
                seen_ids.add(sid)

        # Strategy 3: Graph search
        graph_symbols = self._identify_via_graph_search(repo_id, query, effective_config)
        for sid in graph_symbols:
            if sid not in seen_ids:
                symbol_ids.append(sid)
                seen_ids.add(sid)

        return symbol_ids

    def _identify_via_vector_search(
        self, repo_id: str, query: str, config: Optional[RetrievalConfig] = None
    ) -> List[str]:
        """Identify symbols via vector similarity search."""
        effective_config = config or self._config
        try:
            query_embedding = self._embedding_generator.embed(query)

            # Use configured top_k instead of hardcoded 10
            # Limit to reasonable max for starting symbols (e.g., 50% of top_k)
            symbol_search_top_k = min(effective_config.top_k_vector // 2, 200)

            results = self._vector_store.search(
                query_embedding=query_embedding,
                repo_id=repo_id,
                top_k=symbol_search_top_k,
            )

            symbol_ids = []
            for result in results:
                symbols_defined = result.metadata.get("symbols_defined", "")
                if symbols_defined:
                    if isinstance(symbols_defined, list):
                        symbol_names = symbols_defined
                    else:
                        symbol_names = [
                            s.strip() for s in symbols_defined.split(",") if s.strip()
                        ]

                    # Use configured limit for symbols per chunk
                    max_symbols = effective_config.max_symbols_per_chunk
                    for symbol_name in symbol_names[:max_symbols]:
                        resolved_ids = self._symbol_adapter.search_symbols_by_name(
                            repo_id, symbol_name
                        )
                        # Use configured limit for resolved IDs per symbol
                        max_ids = effective_config.max_resolved_ids_per_symbol
                        symbol_ids.extend(resolved_ids[:max_ids])

            return symbol_ids

        except Exception as e:
            logger.warning("Vector search failed: %s", e)
            return []

    def _identify_via_pattern_matching(
        self, repo_id: str, query: str
    ) -> List[str]:
        """Identify symbols by matching patterns in query."""
        potential_names: Set[str] = set()

        # CamelCase pattern
        camel_case = re.findall(
            r"\b([A-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+)\b", query
        )
        potential_names.update(camel_case)

        # snake_case pattern
        snake_case = re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", query)
        potential_names.update(snake_case)

        # Quoted strings
        quoted = re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', query)
        potential_names.update(quoted)

        # Single capitalized words
        single_caps = re.findall(r"\b([A-Z][a-z][a-zA-Z0-9]*)\b", query)
        potential_names.update(single_caps)

        symbol_ids = []
        for name in potential_names:
            try:
                symbols = self._symbol_adapter.search_symbols_by_name(repo_id, name)
                symbol_ids.extend(symbols)
            except Exception as e:
                logger.debug("Failed to search for symbol %s: %s", name, e)

        return symbol_ids

    def _identify_via_graph_search(
        self, repo_id: str, query: str, config: Optional[RetrievalConfig] = None
    ) -> List[str]:
        """Identify symbols by searching the graph."""
        effective_config = config or self._config
        stop_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "function",
            "class",
            "method",
            "module",
            "file",
            "code",
        }

        words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", query.lower())
        terms = [w for w in words if w not in stop_words and len(w) > 2]

        if not terms:
            return []

        symbol_ids = []
        # Use configured limit for number of search terms
        max_terms = effective_config.max_entry_points_traced
        for term in terms[:max_terms]:
            try:
                symbols = self._symbol_adapter.search_symbols_by_name(repo_id, term)
                symbol_ids.extend(symbols)
            except Exception as e:
                logger.debug("Failed to search for term %s: %s", term, e)

        return symbol_ids

    # =========================================================================
    # Internal Methods - Graph RAG Expansion
    # =========================================================================

    def _expand_and_build_packets(
        self,
        repo_id: str,
        symbol_ids: List[str],
        max_depth: int,
    ) -> Tuple[List[ContextPacket], List[GraphNode], List]:
        """Expand graph neighborhoods and build context packets."""
        packets: List[ContextPacket] = []
        all_nodes: List[GraphNode] = []
        all_edges = []
        seen_node_ids: Set[str] = set()
        seen_edge_keys: Set[tuple] = set()

        for symbol_id in symbol_ids:
            try:
                result = self._traversal_adapter.get_reachable_subgraph(
                    start_id=symbol_id,
                    max_depth=max_depth,
                    allowed_edges=None,  # Let adapter determine appropriate edges
                    direction="both",
                )

                # Collect unique nodes
                if result.nodes:
                    for node in result.nodes:
                        if node.id not in seen_node_ids:
                            all_nodes.append(node)
                            seen_node_ids.add(node.id)

                # Collect unique edges
                if result.edges:
                    for edge in result.edges:
                        edge_key = (edge.source_id, edge.target_id, edge.edge_type)
                        if edge_key not in seen_edge_keys:
                            all_edges.append(edge)
                            seen_edge_keys.add(edge_key)

                # Build context packet
                if result.nodes:
                    packet = self._packet_builder.build_packet(
                        traversal_result=result,
                        root_symbol=symbol_id,
                    )
                    packets.append(packet)

            except Exception as e:
                logger.error(f"Error expanding symbol {symbol_id}: {e}")
                continue

        return packets, all_nodes, all_edges

    def _build_vis_graph(
        self, nodes: List[GraphNode], edges: List
    ) -> Optional[VisGraph]:
        """Build VisGraph for interactive visualization."""
        if not nodes:
            return None

        try:
            vis_nodes: List[VisNode] = []
            vis_edges: List[VisEdge] = []

            for node in nodes:
                vis_nodes.append(VisNode.from_graph_node(node))

            node_ids = {node.id for node in nodes}
            for edge in edges:
                if edge.source_id in node_ids and edge.target_id in node_ids:
                    try:
                        edge_type = GraphEdgeType(edge.edge_type)
                    except ValueError:
                        edge_type = GraphEdgeType.CALLS

                    vis_edges.append(
                        VisEdge(
                            source=edge.source_id,
                            target=edge.target_id,
                            edge_type=edge_type,
                        )
                    )

            return VisGraph(nodes=vis_nodes, edges=vis_edges)

        except Exception as e:
            logger.warning(f"Failed to build VisGraph: {e}")
            return None

    # =========================================================================
    # Internal Methods - Domain Queries
    # =========================================================================

    def _detect_domain_query(self, query: str) -> Optional[str]:
        """Detect if query is asking about a domain/module/directory."""
        domain_patterns = [
            r"how does (?:the )?(\w+) (?:domain|module|package|folder|directory) work",
            r"what is (?:the )?(\w+) (?:domain|module|package|folder|directory)",
            r"explain (?:the )?(\w+) (?:domain|module|package|folder|directory)",
            r"overview of (?:the )?(\w+)",
            r"architecture of (?:the )?(\w+)",
        ]

        query_lower = query.lower()
        for pattern in domain_patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(1)

        return None

    def _retrieve_domain(
        self,
        repo_id: str,
        domain_name: str,
        query: str,
        max_tokens: int,
        config: Optional[RetrievalConfig] = None,
    ) -> RetrievalResponse:
        """Retrieve context for a domain-level query."""
        effective_config = config or self._config
        # Simplified implementation
        # TODO: Add directory summary support through adapter
        logger.info(f"Domain query detected: {domain_name}, falling back to standard retrieval")

        candidates = self._vector_search(repo_id, query, effective_config)
        candidates = self._expand_via_graph(repo_id, candidates, effective_config)
        ranked = self._rank_candidates(candidates, effective_config)
        pruned = self._prune_to_token_limit(ranked, max_tokens)
        context_items = self._build_context_items(pruned)

        return RetrievalResponse(context_items=context_items)
