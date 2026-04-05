"""Get flow between symbols tool for the chat agent.

This module provides the get_flow_between_symbols tool that finds
the call/import path connecting two symbols in the code graph.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..analysis import (
    RepositoryNotFoundError,
    RepositoryNotReadyError,
    SymbolNotFoundError,
)
from ..services.query_service import CodeQueryService

logger = EnhancedLogger(__name__)


@dataclass
class FlowResult:
    """Result from a get_flow_between_symbols tool invocation."""

    success: bool
    path: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    error: Optional[str] = None


class GetFlowBetweenSymbolsTool:
    """Tool for finding the call/import path between two symbols.

    This tool uses the GraphQueryService to find connections
    between symbols via CALLS and IMPORTS edges.
    """

    # Tool schema for LLM function calling
    SCHEMA = {
        "name": "get_flow_between_symbols",
        "description": "Find the call/import path connecting two symbols in the codebase.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "from_symbol": {
                    "type": "string",
                    "description": "The starting symbol name or ID.",
                },
                "to_symbol": {
                    "type": "string",
                    "description": "The target symbol name or ID.",
                },
                "max_hops": {
                    "type": "integer",
                    "description": "Maximum number of hops in the path (default: 5).",
                    "default": 5,
                },
            },
            "required": ["repo_id", "from_symbol", "to_symbol"],
        },
    }

    def __init__(self, query_service: CodeQueryService):
        """Initialize the GetFlowBetweenSymbolsTool.

        Args:
            query_service: The CodeQueryService for graph queries.
        """
        self._query_service = query_service

    def invoke(
        self,
        repo_id: str,
        from_symbol: str,
        to_symbol: str,
        max_hops: int = 5,
    ) -> FlowResult:
        """Invoke the get_flow_between_symbols tool.

        Args:
            repo_id: The repository ID.
            from_symbol: The starting symbol name or ID.
            to_symbol: The target symbol name or ID.
            max_hops: Maximum number of hops in the path.

        Returns:
            FlowResult containing the path or error.
        """
        # Validate repository
        try:
            self._query_service.validate_repository(repo_id)
        except RepositoryNotFoundError as e:
            return FlowResult(success=False, error=str(e))
        except RepositoryNotReadyError as e:
            return FlowResult(success=False, error=str(e))

        try:
            # Resolve symbol IDs if names are provided
            from_id = self._query_service.resolve_symbol_id(repo_id, from_symbol)
            to_id = self._query_service.resolve_symbol_id(repo_id, to_symbol)

            if from_id is None:
                return FlowResult(
                    success=False,
                    error=f"Symbol '{from_symbol}' not found in repository.",
                )

            if to_id is None:
                return FlowResult(
                    success=False,
                    error=f"Symbol '{to_symbol}' not found in repository.",
                )

            # Find path using CALLS and IMPORTS edges
            path_ids = self._query_service.find_call_path(
                from_id=from_id,
                to_id=to_id,
                max_hops=max_hops,
            )

            if path_ids is None or len(path_ids) == 0:
                return FlowResult(
                    success=True,
                    path=[],
                    description=f"No path found between '{from_symbol}' and '{to_symbol}' within {max_hops} hops.",
                )

            # Build detailed path with node information
            path_details = self._query_service.build_path_details(path_ids)
            description = self._build_path_description(from_symbol, to_symbol, path_ids)

            return FlowResult(
                success=True,
                path=path_details,
                description=description,
            )

        except SymbolNotFoundError as e:
            return FlowResult(success=False, error=str(e))
        except Exception as e:
            logger.error(
                f"Failed to find path from {from_symbol} to {to_symbol}: {e}",
                exc_info=True,
            )
            return FlowResult(
                success=False,
                error=f"Failed to find path: {str(e)}",
            )

    def _build_path_description(
        self, from_symbol: str, to_symbol: str, path_ids: List[str]
    ) -> str:
        """Build a human-readable description of the path.

        Args:
            from_symbol: The starting symbol.
            to_symbol: The target symbol.
            path_ids: List of node IDs in the path.

        Returns:
            Human-readable path description.
        """
        if len(path_ids) == 0:
            return f"No path found between '{from_symbol}' and '{to_symbol}'."

        if len(path_ids) == 1:
            return f"'{from_symbol}' and '{to_symbol}' are the same symbol."

        # Extract symbol names from IDs
        names = [node_id.split(":")[-1] for node_id in path_ids]
        path_str = " → ".join(names)

        return f"Path from '{from_symbol}' to '{to_symbol}' ({len(path_ids) - 1} hops): {path_str}"

    def format_for_display(self, result: FlowResult) -> str:
        """Format flow result for display to user.

        Args:
            result: The flow result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Failed to find flow: {result.error}"

        if not result.path:
            return f"ℹ️ {result.description}"

        output_parts = [f"**{result.description}**\n"]

        for i, node in enumerate(result.path):
            prefix = "├──" if i < len(result.path) - 1 else "└──"
            name = node.get("name", node.get("id", "unknown"))
            node_type = node.get("type", "unknown")
            file_path = node.get("file_path")

            line = f"{prefix} `{name}` ({node_type})"
            if file_path:
                line += f" in `{file_path}`"

            output_parts.append(line)

        return "\n".join(output_parts)
