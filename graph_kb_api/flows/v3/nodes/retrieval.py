"""
Retrieval nodes for LangGraph v3 workflows.

These nodes provide retrieval functionality including semantic search
and graph-based context expansion using the GraphKB facade.

All nodes follow LangGraph conventions:
- Nodes are callable objects (implement __call__)
- Nodes take state and return state updates
- Nodes are configurable through constructor parameters
"""

from typing import Any, Dict, List, Optional

from langgraph.types import RunnableConfig

from graph_kb_api.flows.v3.state.common import BaseCommandState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class SemanticRetrievalNode:
    """
    Performs semantic retrieval using vector search.

    Uses ChromaDB through the GraphKB facade to find semantically similar
    code chunks based on a query.

    Configuration:
        default_top_k: Default number of results to retrieve
        allow_skip: Whether to allow skipping when GraphKB unavailable

    Example:
        >>> node = SemanticRetrievalNode(default_top_k=20)
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_top_k: int = 10,
        allow_skip: bool = True
    ):
        """
        Initialize semantic retrieval node.

        Args:
            default_top_k: Default number of results to retrieve
            allow_skip: Whether to allow skipping when GraphKB unavailable
        """
        self.node_name = "semantic_retrieval"
        self.default_top_k = default_top_k
        self.allow_skip = allow_skip

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Perform semantic retrieval.

        Args:
            state: Current workflow state (should contain 'query' field)
            config: LangGraph config containing services

        Returns:
            State updates with retrieval results
        """
        logger.info("Performing semantic retrieval")

        # Get query from state
        query = state.get('query') or state.get('original_input') or state.get('refined_question')
        if not query:
            return {
                'error': 'No query provided for semantic retrieval',
                'error_type': 'missing_query',
                'success': False
            }

        # Get repo_id
        repo_id = state.get('repo_id')
        if not repo_id:
            return {
                'error': 'Repository ID required for semantic retrieval',
                'error_type': 'missing_repo_id',
                'success': False
            }

        # Extract services from config
        services = {}
        if config and 'configurable' in config:
            services = config['configurable'].get('services', {})

        # Get app context
        app_context = services.get('app_context')
        if not app_context:
            return {
                'error': 'Application context not available',
                'error_type': 'service_unavailable',
                'success': False
            }

        try:
            # Get GraphKB facade
            if not hasattr(app_context, 'graph_kb_facade') or not app_context.graph_kb_facade:
                logger.warning("GraphKB facade not available, skipping semantic retrieval")
                if self.allow_skip:
                    return {
                        'semantic_results': [],
                        'retrieval_skipped': True,
                        'retrieval_reason': 'graph_kb_not_available'
                    }
                else:
                    return {
                        'error': 'GraphKB not available',
                        'error_type': 'service_unavailable',
                        'success': False
                    }

            facade = app_context.graph_kb_facade

            # Perform semantic search
            results = await self._perform_semantic_search(facade, query, repo_id, state)

            logger.info(f"Semantic retrieval found {len(results)} results")

            return {
                'semantic_results': results,
                'retrieval_performed': True,
                'retrieval_query': query,
                'result_count': len(results)
            }

        except Exception as e:
            logger.error(f"Semantic retrieval failed: {e}")
            return {
                'error': f"Semantic retrieval error: {str(e)}",
                'error_type': 'retrieval_error',
                'success': False,
                'semantic_results': []
            }

    async def _perform_semantic_search(
        self,
        facade,
        query: str,
        repo_id: str,
        state: BaseCommandState
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search using the GraphKB facade.

        Args:
            facade: GraphKB facade instance
            query: Search query
            repo_id: Repository identifier
            state: Current workflow state

        Returns:
            List of search results
        """
        # Get top_k from state or use default
        top_k = state.get('max_results', self.default_top_k)

        # Try different retrieval service methods based on what's available
        if hasattr(facade, 'retrieval_service'):
            retrieval_service = facade.retrieval_service

            # Try semantic search method
            if hasattr(retrieval_service, 'semantic_search'):
                results = await retrieval_service.semantic_search(
                    query=query,
                    repo_id=repo_id,
                    top_k=top_k
                )
                return self._format_search_results(results)

            # Try retrieve_context method
            if hasattr(retrieval_service, 'retrieve_context'):
                context, chunks = await retrieval_service.retrieve_context(
                    query=query,
                    repo_id=repo_id,
                    top_k=top_k
                )
                return self._format_chunks_as_results(chunks)

        # Fallback: return empty results
        logger.warning("No suitable retrieval method found on facade")
        return []

    def _format_search_results(self, results: Any) -> List[Dict[str, Any]]:
        """
        Format search results into a consistent structure.

        Args:
            results: Raw search results

        Returns:
            Formatted list of result dictionaries
        """
        if not results:
            return []

        formatted = []

        # Handle different result formats
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    formatted.append(item)
                elif hasattr(item, '__dict__'):
                    formatted.append(vars(item))
                else:
                    formatted.append({'content': str(item)})

        return formatted

    def _format_chunks_as_results(self, chunks: Any) -> List[Dict[str, Any]]:
        """
        Format chunks into result dictionaries.

        Args:
            chunks: Chunk objects or dictionaries

        Returns:
            Formatted list of result dictionaries
        """
        if not chunks:
            return []

        formatted = []

        for chunk in chunks:
            if isinstance(chunk, dict):
                formatted.append(chunk)
            elif hasattr(chunk, '__dict__'):
                formatted.append(vars(chunk))
            else:
                formatted.append({'content': str(chunk)})

        return formatted


class GraphRAGExpansionNode:
    """
    Expands context using graph relationships.

    Takes initial retrieval results and expands them by following
    graph relationships (calls, imports, etc.) to gather additional context.

    Configuration:
        default_max_depth: Default expansion depth
        allow_skip: Whether to allow skipping when GraphKB unavailable

    Example:
        >>> node = GraphRAGExpansionNode(default_max_depth=2)
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_max_depth: int = 1,
        allow_skip: bool = True
    ):
        """
        Initialize graph RAG expansion node.

        Args:
            default_max_depth: Default expansion depth
            allow_skip: Whether to allow skipping when GraphKB unavailable
        """
        self.node_name = "graph_rag_expansion"
        self.default_max_depth = default_max_depth
        self.allow_skip = allow_skip

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Perform graph RAG expansion.

        Args:
            state: Current workflow state (should contain 'semantic_results')
            config: LangGraph config containing services

        Returns:
            State updates with expanded context
        """
        logger.info("Performing graph RAG expansion")

        # Get initial results
        semantic_results = state.get('semantic_results', [])
        if not semantic_results:
            logger.info("No semantic results to expand")
            return {
                'expanded_context': [],
                'expansion_performed': False,
                'expansion_reason': 'no_initial_results'
            }

        # Get repo_id
        repo_id = state.get('repo_id')
        if not repo_id:
            return {
                'error': 'Repository ID required for graph expansion',
                'error_type': 'missing_repo_id',
                'success': False
            }

        # Extract services from config
        services = {}
        if config and 'configurable' in config:
            services = config['configurable'].get('services', {})

        # Get app context
        app_context = services.get('app_context')
        if not app_context:
            return {
                'error': 'Application context not available',
                'error_type': 'service_unavailable',
                'success': False
            }

        try:
            # Get GraphKB facade
            if not hasattr(app_context, 'graph_kb_facade') or not app_context.graph_kb_facade:
                logger.warning("GraphKB facade not available, skipping graph expansion")
                if self.allow_skip:
                    return {
                        'expanded_context': semantic_results,
                        'expansion_skipped': True,
                        'expansion_reason': 'graph_kb_not_available'
                    }
                else:
                    return {
                        'error': 'GraphKB not available',
                        'error_type': 'service_unavailable',
                        'success': False
                    }

            facade = app_context.graph_kb_facade

            # Perform graph expansion
            expanded_results = await self._perform_graph_expansion(
                facade, semantic_results, repo_id, state
            )

            logger.info(f"Graph expansion added {len(expanded_results) - len(semantic_results)} additional items")

            return {
                'expanded_context': expanded_results,
                'expansion_performed': True,
                'original_count': len(semantic_results),
                'expanded_count': len(expanded_results)
            }

        except Exception as e:
            logger.error(f"Graph expansion failed: {e}")
            # Return original results if expansion fails
            return {
                'expanded_context': semantic_results,
                'expansion_failed': True,
                'expansion_error': str(e)
            }

    async def _perform_graph_expansion(
        self,
        facade,
        initial_results: List[Dict[str, Any]],
        repo_id: str,
        state: BaseCommandState
    ) -> List[Dict[str, Any]]:
        """
        Expand results using graph relationships.

        Args:
            facade: GraphKB facade instance
            initial_results: Initial search results
            repo_id: Repository identifier
            state: Current workflow state

        Returns:
            Expanded list of results
        """
        # Start with initial results
        expanded = list(initial_results)

        # Get expansion depth from state or use default
        max_depth = state.get('expansion_depth', self.default_max_depth)

        # Try to use graph expansion service
        if hasattr(facade, 'retrieval_service'):
            retrieval_service = facade.retrieval_service

            # Try graph expansion method
            if hasattr(retrieval_service, 'expand_with_graph'):
                for result in initial_results:
                    # Extract symbol or file information
                    symbol_id = result.get('symbol_id')
                    file_path = result.get('file_path')

                    if symbol_id or file_path:
                        related = await retrieval_service.expand_with_graph(
                            symbol_id=symbol_id,
                            file_path=file_path,
                            repo_id=repo_id,
                            max_depth=max_depth
                        )

                        # Add related items that aren't already in results
                        for item in related:
                            if item not in expanded:
                                expanded.append(item)

        return expanded
