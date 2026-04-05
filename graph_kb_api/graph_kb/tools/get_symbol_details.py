"""Get symbol details tool for the chat agent.

This module provides the get_symbol_details tool that retrieves
detailed information about a specific symbol including its relationships.
"""

from dataclasses import dataclass
from typing import List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..services.query_service import CodeQueryService

logger = EnhancedLogger(__name__)


@dataclass
class SymbolDetail:
    """Detailed information about a symbol."""

    id: str
    name: str
    kind: str
    file_path: str
    line_number: Optional[int] = None
    docstring: Optional[str] = None
    callers_count: Optional[int] = None
    callees_count: Optional[int] = None


@dataclass
class GetSymbolDetailsResult:
    """Result from a get_symbol_details tool invocation."""

    success: bool
    symbols: Optional[List[SymbolDetail]] = None
    error: Optional[str] = None


class GetSymbolDetailsTool:
    """Tool for getting detailed information about a symbol.

    This tool retrieves comprehensive information about a symbol including
    its type, location, documentation, and relationship counts.
    """

    SCHEMA = {
        "name": "get_symbol_details",
        "description": "Get detailed information about a specific symbol (function, class, method) including its location, documentation, and relationship counts (callers/callees).",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "symbol_name": {
                    "type": "string",
                    "description": "The name or pattern to match for the symbol.",
                },
                "include_callers": {
                    "type": "boolean",
                    "description": "Include count of what calls this symbol (default: true).",
                },
                "include_callees": {
                    "type": "boolean",
                    "description": "Include count of what this symbol calls (default: true).",
                },
            },
            "required": ["repo_id", "symbol_name"],
        },
    }

    def __init__(self, query_service: CodeQueryService):
        """Initialize the GetSymbolDetailsTool.

        Args:
            query_service: The CodeQueryService for symbol queries.
        """
        self._query_service = query_service

    def invoke(
        self,
        repo_id: str,
        symbol_name: str,
        include_callers: bool = True,
        include_callees: bool = True,
    ) -> GetSymbolDetailsResult:
        """Invoke the get_symbol_details tool.

        Args:
            repo_id: The repository ID.
            symbol_name: The symbol name to find details for.
            include_callers: Whether to include caller count.
            include_callees: Whether to include callee count.

        Returns:
            GetSymbolDetailsResult containing symbol details or error.
        """
        try:
            # Validate repository
            self._query_service.validate_repository(repo_id)

            # Find matching symbols using pattern search
            matches = self._query_service.get_symbols_by_pattern(
                repo_id=repo_id,
                name_pattern=symbol_name,
                limit=5,  # Limit to first 5 matches
            )

            if not matches:
                return GetSymbolDetailsResult(
                    success=False,
                    error=f"Symbol '{symbol_name}' not found in repository.",
                )

            # Build detailed information for each match
            symbol_details = []
            for match in matches:
                detail = SymbolDetail(
                    id=match.id,
                    name=match.name,
                    kind=match.kind,
                    file_path=match.file_path,
                    docstring=match.docstring,
                )

                # Get relationship counts if requested
                if include_callers or include_callees:
                    try:
                        neighborhood = self._query_service.get_bidirectional_neighborhood(
                            node_id=match.id,
                            max_depth=1,
                            repo_id=repo_id,
                        )

                        if include_callers:
                            # Count incoming edges (callers)
                            detail.callers_count = len([
                                e for e in neighborhood.edges
                                if e.target_id == match.id
                            ])

                        if include_callees:
                            # Count outgoing edges (callees)
                            detail.callees_count = len([
                                e for e in neighborhood.edges
                                if e.source_id == match.id
                            ])

                    except Exception as e:
                        logger.warning(f"Failed to get relationships for {match.id}: {e}")
                        # Continue without relationship counts

                symbol_details.append(detail)

            return GetSymbolDetailsResult(
                success=True,
                symbols=symbol_details,
            )

        except Exception as e:
            logger.error(f"Failed to get symbol details: {e}", exc_info=True)
            return GetSymbolDetailsResult(
                success=False,
                error=f"Failed to get symbol details: {str(e)}",
            )

    def format_for_display(self, result: GetSymbolDetailsResult) -> str:
        """Format result for display to user.

        Args:
            result: The symbol details result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ {result.error}"

        if not result.symbols:
            return "ℹ️ No symbols found."

        output = [f"**Found {len(result.symbols)} symbol(s):**\n"]

        for i, symbol in enumerate(result.symbols, 1):
            output.append(f"**{i}. `{symbol.name}`** ({symbol.kind})")
            output.append(f"   📁 `{symbol.file_path}`")

            if symbol.line_number:
                output.append(f"   📍 Line {symbol.line_number}")

            # Relationship counts
            if symbol.callers_count is not None or symbol.callees_count is not None:
                relationships = []
                if symbol.callers_count is not None:
                    relationships.append(f"⬅️  {symbol.callers_count} callers")
                if symbol.callees_count is not None:
                    relationships.append(f"➡️  {symbol.callees_count} callees")
                output.append(f"   {' | '.join(relationships)}")

            # Docstring (truncated)
            if symbol.docstring:
                doc_preview = symbol.docstring[:150]
                if len(symbol.docstring) > 150:
                    doc_preview += "..."
                output.append(f"   📝 {doc_preview}")

            output.append("")

        return "\n".join(output)
