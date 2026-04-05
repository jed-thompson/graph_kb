"""Get symbol references tool for the chat agent.

This module provides the get_symbol_references tool that finds
callers (who calls this?) and callees (what does this call?).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..analysis import (
    RepositoryNotFoundError,
    RepositoryNotReadyError,
)
from ..models.enums import GraphEdgeType
from ..services.query_service import CodeQueryService

logger = EnhancedLogger(__name__)


@dataclass
class SymbolReferencesResult:
    """Result from a get_symbol_references tool invocation."""

    success: bool
    symbol_name: Optional[str] = None
    references: Optional[List[Dict[str, Any]]] = None
    direction: Optional[str] = None
    error: Optional[str] = None


class GetSymbolReferencesTool:
    """Tool for finding symbol callers and callees.

    This tool answers questions like:
    - "What functions call this function?" (callers)
    - "What does this function call?" (callees)
    - "What imports this module?" (importers)
    - "What does this module import?" (imports)
    """

    SCHEMA = {
        "name": "get_symbol_references",
        "description": "Find what calls a symbol (callers) or what a symbol calls (callees). Also works for imports.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "symbol_name": {
                    "type": "string",
                    "description": "The name of the symbol (function, class, or module) to find references for.",
                },
                "direction": {
                    "type": "string",
                    "description": "Direction of references: 'callers' (who calls this), 'callees' (what this calls), 'importers' (who imports this), 'imports' (what this imports).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 20).",
                },
            },
            "required": ["repo_id", "symbol_name", "direction"],
        },
    }

    def __init__(
        self,
        query_service: CodeQueryService,
    ):
        """Initialize the GetSymbolReferencesTool.

        Args:
            query_service: The CodeQueryService for validation and queries.
        """
        self._query_service = query_service

    def invoke(
        self,
        repo_id: str,
        symbol_name: str,
        direction: str,
        max_results: int = 20,
    ) -> SymbolReferencesResult:
        """Invoke the get_symbol_references tool.

        Args:
            repo_id: The repository ID.
            symbol_name: The symbol name to find references for.
            direction: 'callers', 'callees', 'importers', or 'imports'.
            max_results: Maximum results to return.

        Returns:
            SymbolReferencesResult containing references or error.
        """
        # Validate repository
        try:
            self._query_service.validate_repository(repo_id)
        except RepositoryNotFoundError as e:
            return SymbolReferencesResult(success=False, error=str(e))
        except RepositoryNotReadyError as e:
            return SymbolReferencesResult(success=False, error=str(e))

        # Validate direction
        valid_directions = ["callers", "callees", "importers", "imports"]
        if direction.lower() not in valid_directions:
            return SymbolReferencesResult(
                success=False,
                error=f"Invalid direction '{direction}'. Must be one of: {valid_directions}",
            )

        try:
            # Resolve symbol to ID
            symbol_id = self._query_service.resolve_symbol_id(repo_id, symbol_name)
            if not symbol_id:
                return SymbolReferencesResult(
                    success=False,
                    error=f"Symbol '{symbol_name}' not found in repository.",
                )

            # Determine edge types and direction
            direction_lower = direction.lower()
            if direction_lower in ["callers", "callees"]:
                edge_types = [GraphEdgeType.CALLS.value]
                graph_direction = "incoming" if direction_lower == "callers" else "outgoing"
            else:  # importers, imports
                edge_types = [GraphEdgeType.IMPORTS.value]
                graph_direction = "incoming" if direction_lower == "importers" else "outgoing"

            # Get neighbors using CodeQueryService
            neighbors = self._query_service.get_neighbors(
                node_id=symbol_id,
                edge_types=edge_types,
                direction=graph_direction,
                limit=max_results,
            )

            # Format results
            references = []
            for node in neighbors:
                ref = {
                    "name": node.name,
                    "file_path": node.file_path,
                    "kind": node.kind.value if node.kind else "unknown",
                    "line_number": node.start_line,
                }
                if node.docstring:
                    ref["docstring"] = node.docstring[:200]  # Truncate
                references.append(ref)

            return SymbolReferencesResult(
                success=True,
                symbol_name=symbol_name,
                references=references,
                direction=direction_lower,
            )

        except Exception as e:
            logger.error(f"Failed to get symbol references: {e}", exc_info=True)
            return SymbolReferencesResult(
                success=False,
                error=f"Failed to get references: {str(e)}",
            )

    def format_for_display(self, result: SymbolReferencesResult) -> str:
        """Format result for display."""
        if not result.success:
            return f"❌ {result.error}"

        if not result.references:
            direction_text = {
                "callers": "Nothing calls",
                "callees": "doesn't call anything",
                "importers": "Nothing imports",
                "imports": "doesn't import anything",
            }.get(result.direction, "No references for")
            return f"ℹ️ {direction_text} `{result.symbol_name}`"

        direction_text = {
            "callers": "Functions that call",
            "callees": "Functions called by",
            "importers": "Modules that import",
            "imports": "Modules imported by",
        }.get(result.direction, "References for")

        output = [f"**{direction_text} `{result.symbol_name}`** ({len(result.references)}):\n"]

        for ref in result.references:
            line = f"  • `{ref['name']}` ({ref['kind']}) in `{ref['file_path']}`"
            if ref.get("line_number"):
                line += f" L{ref['line_number']}"
            output.append(line)

        return "\n".join(output)
