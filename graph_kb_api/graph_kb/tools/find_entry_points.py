"""Find entry points tool for the chat agent.

This module provides the find_entry_points tool that discovers
HTTP endpoints, CLI commands, main functions, and event handlers.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.analysis_enums import EntryPointType
from ..services.analysis_service import CodeAnalysisService

logger = EnhancedLogger(__name__)


@dataclass
class EntryPointInfo:
    """DTO for entry point information."""

    name: str
    file_path: str
    type: str
    line_number: Optional[int]
    http_method: Optional[str]
    description: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "file_path": self.file_path,
            "type": self.type,
            "line_number": self.line_number,
            "http_method": self.http_method,
            "description": self.description,
        }


@dataclass
class FindEntryPointsResult:
    """Result from a find_entry_points tool invocation."""

    success: bool
    entry_points: Optional[List[EntryPointInfo]] = None
    error: Optional[str] = None


class FindEntryPointsTool:
    """Tool for discovering entry points in a repository.

    Entry points include HTTP endpoints, CLI commands, main functions,
    event handlers, and scheduled tasks.
    """

    SCHEMA = {
        "name": "find_entry_points",
        "description": "Find entry points in a repository such as HTTP endpoints, CLI commands, main functions, and event handlers.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "entry_type": {
                    "type": "string",
                    "description": "Optional filter by entry point type: 'http', 'cli', 'main', 'event', 'scheduled', or 'all' (default).",
                },
                "folder_path": {
                    "type": "string",
                    "description": "Optional folder path to limit the search scope (e.g., 'src/api/').",
                },
            },
            "required": ["repo_id"],
        },
    }

    def __init__(
        self,
        analysis_service: CodeAnalysisService,
    ):
        """Initialize the FindEntryPointsTool.

        Args:
            analysis_service: The CodeAnalysisService for analysis operations.
        """
        self._analysis_service = analysis_service

    def invoke(
        self,
        repo_id: str,
        entry_type: Optional[str] = None,
        folder_path: Optional[str] = None,
    ) -> FindEntryPointsResult:
        """Invoke the find_entry_points tool.

        Args:
            repo_id: The repository ID.
            entry_type: Optional filter by type ('http', 'cli', 'main', 'event', 'scheduled').
            folder_path: Optional folder path to limit scope.

        Returns:
            FindEntryPointsResult containing entry points or error.
        """
        try:
            # Analyze entry points using CodeAnalysisService
            entry_points = self._analysis_service.analyze_entry_points(
                repo_id=repo_id,
                folder_path=folder_path,
            )

            # Filter by type if specified
            if entry_type and entry_type.lower() != "all":
                type_map = {
                    "http": EntryPointType.HTTP_ENDPOINT,
                    "cli": EntryPointType.CLI_COMMAND,
                    "main": EntryPointType.MAIN_FUNCTION,
                    "event": EntryPointType.EVENT_HANDLER,
                    "scheduled": EntryPointType.SCHEDULED_TASK,
                }
                filter_type = type_map.get(entry_type.lower())
                if filter_type:
                    entry_points = [
                        ep for ep in entry_points
                        if ep.entry_type == filter_type
                    ]

            results: List[EntryPointInfo] = [
                EntryPointInfo(
                    name=ep.name,
                    file_path=ep.file_path,
                    type=ep.entry_type.value,
                    line_number=ep.line_number,
                    http_method=ep.http_method,
                    description=ep.description,
                )
                for ep in entry_points
            ]

            return FindEntryPointsResult(success=True, entry_points=results)

        except Exception as e:
            logger.error(f"Failed to find entry points: {e}", exc_info=True)
            return FindEntryPointsResult(
                success=False,
                error=f"Failed to find entry points: {str(e)}",
            )

    def format_for_display(self, result: FindEntryPointsResult) -> str:
        """Format result for display."""
        if not result.success:
            return f"❌ {result.error}"

        if not result.entry_points:
            return "No entry points found."

        # Group by type
        by_type: Dict[str, List[EntryPointInfo]] = {}
        for ep in result.entry_points:
            if ep.type not in by_type:
                by_type[ep.type] = []
            by_type[ep.type].append(ep)

        output = [f"Found {len(result.entry_points)} entry points:\n"]
        for ep_type, eps in sorted(by_type.items()):
            output.append(f"\n**{ep_type}** ({len(eps)}):")
            for ep in eps[:10]:  # Limit display
                line = f"  • `{ep.name}` in `{ep.file_path}`"
                if ep.http_method:
                    line += f" [{ep.http_method}]"
                output.append(line)
            if len(eps) > 10:
                output.append(f"  ... and {len(eps) - 10} more")


        return "\n".join(output)
