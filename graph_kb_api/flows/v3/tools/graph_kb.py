"""
GraphKB tools for LangGraph v3 agentic workflows.

This module provides LangChain tools that query the Neo4j graph knowledge base
for code relationships, symbols, and call chains.

Tools are created via factory functions that accept user's retrieval configuration,
ensuring tools respect user preferences from the Chainlit UI.

LangGraph Ref: https://docs.langchain.com/oss/python/langchain/tools
"""

import json
from typing import List, Optional

from langchain_core.tools import tool

from graph_kb_api.graph_kb.facade import GraphKBFacade
from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig
from graph_kb_api.graph_kb.querying.traversal_utils import PathExtractor
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


def create_graph_kb_tools(retrieval_config: RetrievalConfig) -> List:
    """
    Factory function to create GraphKB tools with user's retrieval configuration.

    This ensures tools respect user preferences configured in the Chainlit UI
    (top_k, max_depth, etc.) rather than using hardcoded defaults.

    Args:
        retrieval_config: User's retrieval configuration from app_context

    Returns:
        List of configured tools
    """
    # Get facade instance once for all tools (singleton pattern)
    facade: GraphKBFacade = GraphKBFacade.get_instance()

    @tool
    async def search_code(query: str, repo_id: str, top_k: Optional[int] = None) -> str:
        """Search for code patterns using semantic search in ChromaDB.

        This tool performs semantic search to find code chunks similar to the query.
        Use this when you need to find code based on natural language descriptions
        or when looking for similar functionality.

        Args:
            query: Search query string describing what code to find
            repo_id: Repository identifier
            top_k: Number of results to return (optional - uses user's configured value if not specified)

        Returns:
            JSON string with search results including file paths, content, and scores

        Example:
            >>> search_code("user authentication logic", "my-repo")
            >>> # Returns code chunks using user's configured top_k setting
            >>> search_code("user authentication logic", "my-repo", 20)
            >>> # Returns exactly 20 results
        """
        try:
            # Use provided top_k or fall back to user's configured value
            effective_top_k = top_k if top_k is not None else retrieval_config.top_k_vector

            # For deep agent, allow very large result sets (cap at 1000)
            effective_top_k = min(effective_top_k, 1000)

            logger.info(
                "Executing search_code tool",
                data={'query': query, 'repo_id': repo_id, 'top_k': effective_top_k}
            )

            # Use retrieve_with_progress with user's full config
            result = await facade.retrieval_service.retrieve_with_progress(
                repo_id=repo_id,
                query=query,
                anchors=None,
                config=retrieval_config,  # Use user's full config
                progress_callback=None  # No progress callback for tool calls
            )

            # Format results from context items
            formatted_results = []
            for item in result.context_items[:effective_top_k]:
                formatted_results.append({
                    'file_path': item.file_path or '',
                    'content': item.content or '',
                    'score': item.score or 0.0,
                    'line_number': item.start_line,
                    'symbol_name': item.symbol or '',
                    'chunk_type': item.type.value if hasattr(item.type, 'value') else str(item.type)
                })

            logger.info(
                "search_code completed",
                data={'result_count': len(formatted_results), 'top_k_used': effective_top_k}
            )

            return json.dumps(formatted_results, indent=2)

        except Exception as e:
            logger.error(f"search_code failed: {e}")
            return json.dumps({
                'error': str(e),
                'error_type': type(e).__name__
            })

    @tool
    def get_symbol_info(
        symbol_name: str,
        repo_id: str,
        include_callers: bool = False,
        include_callees: bool = False,
        limit: Optional[int] = None
    ) -> str:
        """Get detailed information about a code symbol.

        This tool retrieves information about a specific function, class, or method
        from the graph knowledge base. Use this when you need details about a
        specific symbol or want to understand its relationships.

        Args:
            symbol_name: Name of the symbol (function, class, method)
            repo_id: Repository identifier
            include_callers: Include functions that call this symbol
            include_callees: Include functions this symbol calls
            limit: Maximum number of callers/callees to return (optional - uses user's configured value if not specified)

        Returns:
            JSON string with symbol details, location, and relationships
        """
        try:
            # Use provided limit or fall back to user's configured value
            # max_expansion_nodes is appropriate for neighbor expansion
            effective_limit = limit if limit is not None else retrieval_config.max_expansion_nodes

            logger.info(
                "Executing get_symbol_info tool",
                data={
                    'symbol_name': symbol_name,
                    'repo_id': repo_id,
                    'include_callers': include_callers,
                    'include_callees': include_callees,
                    'limit': effective_limit
                }
            )

            # Query for symbol using resolve_symbol_id
            symbol_id = facade.query_service.resolve_symbol_id(
                repo_id=repo_id,
                symbol=symbol_name
            )

            if not symbol_id:
                return json.dumps({
                    'error': f"Symbol '{symbol_name}' not found in repository '{repo_id}'",
                    'symbol_name': symbol_name,
                    'repo_id': repo_id
                })

            # Get the symbol node
            symbol_node = facade.query_service.get_node(symbol_id)
            if not symbol_node:
                return json.dumps({
                    'error': f"Symbol node not found for ID '{symbol_id}'",
                    'symbol_id': symbol_id
                })

            # Build result from symbol node
            result = {
                'id': symbol_node.id,
                'name': symbol_node.attrs.get('name', symbol_name),
                'kind': symbol_node.type.value,
                'file_path': symbol_node.attrs.get('file_path'),
                'line_number': symbol_node.attrs.get('line_number'),
                'docstring': symbol_node.attrs.get('docstring'),
                'parameters': symbol_node.attrs.get('parameters', [])
            }

            # Get callers if requested
            if include_callers:
                # Get incoming CALLS edges using get_neighbors
                callers_nodes = facade.query_service.get_neighbors(
                    node_id=symbol_node.id,
                    edge_types=['CALLS'],
                    direction='incoming',
                    limit=effective_limit
                )
                result['callers'] = [
                    {
                        'name': c.attrs.get('name'),
                        'file_path': c.attrs.get('file_path'),
                        'line_number': c.attrs.get('line_number')
                    }
                    for c in callers_nodes
                ]

            # Get callees if requested
            if include_callees:
                # Get outgoing CALLS edges using get_neighbors
                callees_nodes = facade.query_service.get_neighbors(
                    node_id=symbol_node.id,
                    edge_types=['CALLS'],
                    direction='outgoing',
                    limit=effective_limit
                )
                result['callees'] = [
                    {
                        'name': c.attrs.get('name'),
                        'file_path': c.attrs.get('file_path'),
                        'line_number': c.attrs.get('line_number')
                    }
                    for c in callees_nodes
                ]

            logger.info(
                "get_symbol_info completed",
                data={'symbol_found': True}
            )

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"get_symbol_info failed: {e}")
            return json.dumps({
                'error': str(e),
                'error_type': type(e).__name__
            })

    @tool
    def trace_call_chain(
        symbol_name: str,
        repo_id: str,
        direction: str = "outgoing",
        max_depth: Optional[int] = None
    ) -> str:
        """Trace the call chain from/to a specific function.

        This tool traces function call chains to understand data flow and
        dependencies. Use this to see what a function calls (outgoing) or
        what calls a function (incoming).

        Args:
            symbol_name: Starting symbol name
            repo_id: Repository identifier
            direction: "outgoing" (calls) or "incoming" (called by)
            max_depth: Maximum depth to trace (optional - uses user's configured value if not specified)

        Returns:
            JSON string with call chain paths
        """
        try:
            # Use provided max_depth or fall back to user's configured value
            effective_max_depth = max_depth if max_depth is not None else retrieval_config.max_depth

            # For deep agent, allow deeper traversal (cap at 50)
            effective_max_depth = min(effective_max_depth, 50)

            logger.info(
                "Executing trace_call_chain tool",
                data={
                    'symbol_name': symbol_name,
                    'repo_id': repo_id,
                    'direction': direction,
                    'max_depth': effective_max_depth
                }
            )

            # Validate direction
            if direction not in ["outgoing", "incoming"]:
                return json.dumps({
                    'error': f"Invalid direction '{direction}'. Must be 'outgoing' or 'incoming'",
                    'valid_directions': ['outgoing', 'incoming']
                })

            # Find starting symbol
            symbols_results = facade.query_service.get_symbols_by_pattern(
                repo_id=repo_id,
                name_pattern=f"^{symbol_name}$",  # Exact match
                limit=10
            )

            if not symbols_results:
                return json.dumps({
                    'error': f"Symbol '{symbol_name}' not found in repository '{repo_id}'",
                    'symbol_name': symbol_name,
                    'repo_id': repo_id
                })

            symbol_id = symbols_results[0].id

            # Trace call chain using get_reachable_subgraph
            traversal_result = facade.query_service.get_reachable_subgraph(
                start_id=symbol_id,
                max_depth=effective_max_depth,
                allowed_edges=['CALLS'],
                direction=direction,
                repo_id=repo_id
            )

            # Extract paths from traversal result using utility
            formatted_paths = PathExtractor.extract_paths_from_traversal(
                traversal_result=traversal_result,
                start_id=symbol_id,
                direction=direction,
                max_paths=100
            )

            result = {
                'starting_symbol': symbol_name,
                'direction': direction,
                'max_depth': effective_max_depth,
                'path_count': len(formatted_paths),
                'paths': formatted_paths
            }

            logger.info(
                "trace_call_chain completed",
                data={'path_count': len(formatted_paths)}
            )

            return json.dumps(result, indent=2)

        except Exception as e:
            logger.error(f"trace_call_chain failed: {e}")
            return json.dumps({
                'error': str(e),
                'error_type': type(e).__name__
            })

    return [search_code, get_symbol_info, trace_call_chain]


# Backward compatibility: create tools with default config
# These are used when tools are imported directly without factory
_default_tools = create_graph_kb_tools(RetrievalConfig.from_settings())
search_code = _default_tools[0]
get_symbol_info = _default_tools[1]
trace_call_chain = _default_tools[2]
