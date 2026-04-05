"""Search repository tool for the chat agent.

This module provides the search_repo tool that enables semantic search
over indexed repositories using the Retriever.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.base import ContextItem
from ..models.enums import ContextItemType
from ..models.retrieval import RetrievalConfig
from ..services.retrieval_service import CodeRetrievalService

logger = EnhancedLogger(__name__)


@dataclass
class SearchResult:
    """Result from a search_repo tool invocation."""

    success: bool
    chunks: List[Dict[str, Any]]
    error: Optional[str] = None


class SearchRepoTool:
    """Tool for semantic search over indexed repositories.

    This tool integrates with the GraphQueryService for repository validation
    and the Retriever for semantic search, returning formatted code chunks
    and documentation.
    """

    # Tool schema for LLM function calling
    SCHEMA = {
        "name": "search_repo",
        "description": "Search for code and documentation in an indexed repository using semantic search.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository to search.",
                },
                "query": {
                    "type": "string",
                    "description": "The search query describing what you're looking for.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10).",
                    "default": 10,
                },
            },
            "required": ["repo_id", "query"],
        },
    }

    def __init__(
        self,
        retrieval_service: CodeRetrievalService,
    ):
        """Initialize the SearchRepoTool.

        Args:
            retrieval_service: The CodeRetrievalService for semantic search.
        """
        self._retrieval_service = retrieval_service

    def invoke(
        self,
        repo_id: str,
        query: str,
        max_results: int = 10,
        config: Optional[RetrievalConfig] = None,
    ) -> SearchResult:
        """Invoke the search_repo tool.

        Args:
            repo_id: The repository ID to search.
            query: The search query.
            max_results: Maximum number of results to return.
            config: Optional RetrievalConfig to override default settings.

        Returns:
            SearchResult containing formatted chunks or error.
        """
        try:
            # Perform retrieval using CodeRetrievalService
            response = self._retrieval_service.retrieve(
                repo_id=repo_id,
                query=query,
                config=config,
            )

            # Format results
            chunks = self._format_results(response.context_items[:max_results])

            return SearchResult(success=True, chunks=chunks)

        except Exception as e:
            logger.error(f"Search failed for repo {repo_id}: {e}", exc_info=True)
            return SearchResult(
                success=False,
                chunks=[],
                error=f"Search failed: {str(e)}",
            )

    def _format_results(self, context_items: List[ContextItem]) -> List[Dict[str, Any]]:
        """Format context items into response chunks.

        Args:
            context_items: The context items from retrieval.

        Returns:
            List of formatted chunk dictionaries.
        """
        formatted = []

        for item in context_items:
            if item.type == ContextItemType.CHUNK:
                formatted.append(self._format_chunk(item))
            elif item.type == ContextItemType.GRAPH_PATH:
                formatted.append(self._format_graph_path(item))

        return formatted

    def _format_chunk(self, item: ContextItem) -> Dict[str, Any]:
        """Format a chunk context item.

        Args:
            item: The chunk context item.

        Returns:
            Formatted chunk dictionary.
        """
        return {
            "type": "code",
            "file_path": item.file_path,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "content": item.content,
            "symbol": item.symbol,
            "score": round(item.score, 3) if item.score else None,
        }

    def _format_graph_path(self, item: ContextItem) -> Dict[str, Any]:
        """Format a graph path context item.

        Args:
            item: The graph path context item.

        Returns:
            Formatted graph path dictionary.
        """
        return {
            "type": "graph_path",
            "description": item.description,
            "nodes": item.nodes,
        }

    def format_for_display(self, result: SearchResult) -> str:
        """Format search result for display to user.

        Args:
            result: The search result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Search failed: {result.error}"

        if not result.chunks:
            return "No results found for your query."

        output_parts = [f"Found {len(result.chunks)} relevant results:\n"]

        for i, chunk in enumerate(result.chunks, 1):
            if chunk["type"] == "code":
                output_parts.append(
                    f"\n**{i}. {chunk['file_path']}** "
                    f"(lines {chunk['start_line']}-{chunk['end_line']})"
                )
                if chunk.get("symbol"):
                    output_parts.append(f"   Symbol: `{chunk['symbol']}`")
                if chunk.get("content"):
                    # Truncate long content
                    content = chunk["content"]
                    if len(content) > 500:
                        content = content[:500] + "..."
                    output_parts.append(f"```\n{content}\n```")
            elif chunk["type"] == "graph_path":
                output_parts.append(f"\n**{i}. Code Flow:** {chunk['description']}")
                if chunk.get("nodes"):
                    output_parts.append(f"   Path: {' → '.join(chunk['nodes'])}")

        return "\n".join(output_parts)
