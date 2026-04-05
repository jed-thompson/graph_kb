"""Analyze hotspots tool for the chat agent.

This module provides the analyze_hotspots tool that finds
highly-connected code symbols that may need refactoring.
"""

from dataclasses import dataclass
from typing import List, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..services.code_visualization_service import CodeVisualizationService

logger = EnhancedLogger(__name__)


@dataclass
class HotspotInfo:
    """Information about a code hotspot."""

    id: str
    name: str
    file_path: str
    connections: int
    incoming: int
    outgoing: int


@dataclass
class AnalyzeHotspotsResult:
    """Result from an analyze_hotspots tool invocation."""

    success: bool
    hotspots: Optional[List[HotspotInfo]] = None
    total_found: Optional[int] = None
    error: Optional[str] = None


class AnalyzeHotspotsTool:
    """Tool for finding highly-connected code hotspots.

    This tool identifies symbols (functions, classes, methods) with the most
    connections, which may indicate complexity or refactoring opportunities.
    """

    SCHEMA = {
        "name": "analyze_hotspots",
        "description": "Find the most connected symbols (hotspots) in the codebase. Hotspots are functions/classes with many connections, which may indicate complexity or refactoring opportunities.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "folder_path": {
                    "type": "string",
                    "description": "Optional folder path to scope the analysis (e.g., 'src/payments').",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Number of hotspots to return (default: 20).",
                },
            },
            "required": ["repo_id"],
        },
    }

    def __init__(self, visualization_service: CodeVisualizationService):
        """Initialize the AnalyzeHotspotsTool.

        Args:
            visualization_service: The CodeVisualizationService for hotspot analysis.
        """
        self._service = visualization_service

    def invoke(
        self,
        repo_id: str,
        folder_path: Optional[str] = None,
        top_n: int = 20,
    ) -> AnalyzeHotspotsResult:
        """Invoke the analyze_hotspots tool.

        Args:
            repo_id: The repository ID.
            folder_path: Optional folder path to scope the analysis.
            top_n: Number of hotspots to return.

        Returns:
            AnalyzeHotspotsResult containing hotspots or error.
        """
        try:
            # Get hotspots from the service
            vis_graph = self._service.get_hotspots(
                repo_id=repo_id,
                folder_path=folder_path,
                top_n=top_n,
            )

            # Extract hotspot information from nodes
            hotspots = []
            for node in vis_graph.nodes:
                hotspot = HotspotInfo(
                    id=node.id,
                    name=node.label,
                    file_path=node.full_path or "unknown",
                    connections=node.metadata.get("total_connections", 0),
                    incoming=node.metadata.get("incoming_calls", 0),
                    outgoing=node.metadata.get("outgoing_calls", 0),
                )
                hotspots.append(hotspot)

            # Sort by total connections (descending)
            hotspots.sort(key=lambda h: h.connections, reverse=True)

            return AnalyzeHotspotsResult(
                success=True,
                hotspots=hotspots,
                total_found=len(hotspots),
            )

        except Exception as e:
            logger.error(f"Failed to analyze hotspots for repo {repo_id}: {e}", exc_info=True)
            return AnalyzeHotspotsResult(
                success=False,
                error=f"Failed to analyze hotspots: {str(e)}",
            )

    def format_for_display(self, result: AnalyzeHotspotsResult) -> str:
        """Format result for display to user.

        Args:
            result: The hotspots analysis result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Hotspot analysis failed: {result.error}"

        if not result.hotspots:
            return "ℹ️ No hotspots found in the specified scope."

        output = [f"**🔥 Top {len(result.hotspots)} Hotspots** (Total found: {result.total_found})\n"]
        output.append("Symbols with the most connections (potential refactoring candidates):\n")

        for i, hotspot in enumerate(result.hotspots, 1):
            output.append(
                f"{i}. **`{hotspot.name}`** ({hotspot.connections} connections)"
            )
            output.append(f"   📁 `{hotspot.file_path}`")
            output.append(f"   ⬅️  Incoming: {hotspot.incoming} | ➡️  Outgoing: {hotspot.outgoing}")
            output.append("")

        return "\n".join(output)
