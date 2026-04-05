"""Get architecture overview tool for the chat agent.

This module provides the get_architecture_overview tool that returns
a high-level view of the repository's components and their relationships.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..analysis import (
    RepositoryNotFoundError,
    RepositoryNotReadyError,
)
from ..services.query_service import CodeQueryService

logger = EnhancedLogger(__name__)


@dataclass
class ArchitectureResult:
    """Result from a get_architecture_overview tool invocation."""

    success: bool
    modules: Optional[List[Dict[str, Any]]] = None
    relationships: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


class GetArchitectureOverviewTool:
    """Tool for getting a high-level architecture overview of a repository.

    This tool uses the GraphQueryService to retrieve the main
    components/modules and their relationships.
    """

    # Tool schema for LLM function calling
    SCHEMA = {
        "name": "get_architecture_overview",
        "description": "Get a high-level overview of the repository's architecture, including main modules and their relationships.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
            },
            "required": ["repo_id"],
        },
    }

    def __init__(self, query_service: CodeQueryService):
        """Initialize the GetArchitectureOverviewTool.

        Args:
            query_service: The CodeQueryService for graph queries.
        """
        self._query_service = query_service

    def invoke(self, repo_id: str) -> ArchitectureResult:
        """Invoke the get_architecture_overview tool.

        Args:
            repo_id: The repository ID.

        Returns:
            ArchitectureResult containing modules and relationships or error.
        """
        # Validate repository
        try:
            self._query_service.validate_repository(repo_id)
        except RepositoryNotFoundError as e:
            return ArchitectureResult(success=False, error=str(e))
        except RepositoryNotReadyError as e:
            return ArchitectureResult(success=False, error=str(e))

        try:
            # Get architecture overview from query service
            overview = self._query_service.get_architecture(repo_id)

            # Check for empty repository
            if not overview.modules:
                return ArchitectureResult(
                    success=True,
                    modules=[],
                    relationships=[],
                    error=None,
                )

            return ArchitectureResult(
                success=True,
                modules=overview.modules,
                relationships=overview.relationships,
            )

        except Exception as e:
            logger.error(
                f"Failed to get architecture for repo {repo_id}: {e}",
                exc_info=True,
            )
            return ArchitectureResult(
                success=False,
                error=f"Failed to get architecture: {str(e)}",
            )

    def format_for_display(self, result: ArchitectureResult) -> str:
        """Format architecture result for display to user.

        Args:
            result: The architecture result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Failed to get architecture: {result.error}"

        if not result.modules:
            return "ℹ️ No modules found in this repository. The repository may be empty or not yet indexed."

        output_parts = ["**Repository Architecture**\n"]

        # Format modules
        output_parts.append("**Modules:**")
        for module in result.modules:
            name = module.get("name", "unknown")
            file_count = module.get("file_count", 0)
            output_parts.append(f"  • `{name}/` ({file_count} files)")

        # Format relationships if present
        if result.relationships:
            output_parts.append("\n**Key Relationships:**")

            # Group relationships by type
            rel_by_type: Dict[str, List[Dict[str, Any]]] = {}
            for rel in result.relationships:
                rel_type = rel.get("type", "UNKNOWN")
                if rel_type not in rel_by_type:
                    rel_by_type[rel_type] = []
                rel_by_type[rel_type].append(rel)

            for rel_type, rels in rel_by_type.items():
                output_parts.append(f"\n  *{rel_type}:*")
                # Show up to 5 relationships per type
                for rel in rels[:5]:
                    from_file = self._extract_module(rel.get("from_file", ""))
                    to_file = self._extract_module(rel.get("to_file", ""))
                    if from_file and to_file and from_file != to_file:
                        output_parts.append(f"    • `{from_file}` → `{to_file}`")

                if len(rels) > 5:
                    output_parts.append(f"    • ... and {len(rels) - 5} more")

        return "\n".join(output_parts)

    def _extract_module(self, file_path: str) -> str:
        """Extract the module name from a file path.

        Args:
            file_path: The file path.

        Returns:
            The module name (first directory component).
        """
        if not file_path:
            return ""

        parts = file_path.split("/")
        if len(parts) > 1:
            return parts[0]
        return "(root)"
