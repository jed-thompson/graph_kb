"""
Tools initialization for LangGraph v3 workflows.

This module provides a centralized way to initialize and retrieve all tools
used in workflows, ensuring consistent configuration across different workflow types.
"""

from typing import List

from langchain_core.tools import StructuredTool

from graph_kb_api.flows.v3.tools.cypher import execute_cypher_query
from graph_kb_api.flows.v3.tools.file_access import get_file_content, get_related_files
from graph_kb_api.flows.v3.tools.graph_kb import create_graph_kb_tools
from graph_kb_api.flows.v3.tools.websearch import websearch, websearch_with_content
from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig


def get_all_tools(retrieval_config: RetrievalConfig) -> List[StructuredTool]:
    """
    Get all available tools for code analysis workflows.

    This function creates and returns a complete set of tools including:
    - GraphKB tools (semantic search, symbol lookup, etc.)
    - File access tools (read files, find related files)
    - Cypher query tool (direct graph database queries)

    Args:
        retrieval_config: Configuration for retrieval operations (search depth,
                         result limits, etc.)

    Returns:
        List of all available tools configured with the provided settings

    Example:
        >>> from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig
        >>> config = RetrievalConfig.from_settings()
        >>> tools = get_all_tools(config)
        >>> print(f"Loaded {len(tools)} tools")
    """
    # Create GraphKB tools with user's retrieval config
    graph_kb_tools = create_graph_kb_tools(retrieval_config)

    # Combine with other tools
    all_tools = graph_kb_tools + [
        get_file_content,
        get_related_files,
        execute_cypher_query,
        websearch,
        websearch_with_content,
    ]

    return all_tools


__all__ = [
    'get_all_tools',
    'create_graph_kb_tools',
    'get_file_content',
    'get_related_files',
    'execute_cypher_query'
]
