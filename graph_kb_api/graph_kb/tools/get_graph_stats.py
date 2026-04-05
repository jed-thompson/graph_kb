"""Get graph statistics tool for the chat agent.

This module provides the get_graph_stats tool that retrieves
comprehensive statistics about a repository's code graph.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..services.code_visualization_service import CodeVisualizationService

logger = EnhancedLogger(__name__)


@dataclass
class GraphStatsResult:
    """Result from a get_graph_stats tool invocation."""

    success: bool
    total_nodes: Optional[int] = None
    total_edges: Optional[int] = None
    node_counts: Optional[Dict[str, int]] = None
    edge_counts: Optional[Dict[str, int]] = None
    symbol_kinds: Optional[Dict[str, int]] = None
    error: Optional[str] = None


class GetGraphStatsTool:
    """Tool for retrieving comprehensive graph statistics.

    This tool provides detailed statistics about a repository's code graph,
    including node counts, edge counts, symbol kinds, and complexity metrics.
    """

    SCHEMA = {
        "name": "get_graph_stats",
        "description": "Get comprehensive statistics about a repository's code graph, including total nodes/edges, node types, edge types, symbol kinds, and complexity metrics.",
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

    def __init__(self, visualization_service: CodeVisualizationService):
        """Initialize the GetGraphStatsTool.

        Args:
            visualization_service: The CodeVisualizationService for retrieving statistics.
        """
        self._service = visualization_service

    def invoke(self, repo_id: str) -> GraphStatsResult:
        """Invoke the get_graph_stats tool.

        Args:
            repo_id: The repository ID.

        Returns:
            GraphStatsResult containing statistics or error.
        """
        try:
            # Get statistics from the service
            stats = self._service.get_graph_stats(repo_id)

            return GraphStatsResult(
                success=True,
                total_nodes=stats.total_nodes,
                total_edges=stats.total_edges,
                node_counts=stats.node_counts,
                edge_counts=stats.edge_counts,
                symbol_kinds=stats.symbol_kinds,
            )

        except Exception as e:
            logger.error(f"Failed to get graph stats for repo {repo_id}: {e}", exc_info=True)
            return GraphStatsResult(
                success=False,
                error=f"Failed to get graph statistics: {str(e)}",
            )

    def format_for_display(self, result: GraphStatsResult) -> str:
        """Format result for display to user.

        Args:
            result: The graph stats result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Failed to get statistics: {result.error}"

        output = ["**📊 Graph Statistics**\n"]

        # Overall counts
        output.append(f"**Total Nodes:** {result.total_nodes:,}")
        output.append(f"**Total Edges:** {result.total_edges:,}\n")

        # Node type breakdown
        if result.node_counts:
            output.append("**Node Types:**")
            for node_type, count in sorted(result.node_counts.items(), key=lambda x: x[1], reverse=True):
                output.append(f"  • {node_type}: {count:,}")
            output.append("")

        # Edge type breakdown
        if result.edge_counts:
            output.append("**Edge Types:**")
            for edge_type, count in sorted(result.edge_counts.items(), key=lambda x: x[1], reverse=True):
                output.append(f"  • {edge_type}: {count:,}")
            output.append("")

        # Symbol kinds breakdown
        if result.symbol_kinds:
            output.append("**Symbol Kinds:**")
            for kind, count in sorted(result.symbol_kinds.items(), key=lambda x: x[1], reverse=True):
                output.append(f"  • {kind}: {count:,}")

        return "\n".join(output)
