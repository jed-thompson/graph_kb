"""Visualize graph tool for the chat agent.

This module provides the visualize_graph tool that generates
interactive HTML visualizations of code structure.
"""

from dataclasses import dataclass
from typing import Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.visualization import VisualizationType
from ..services.code_visualization_service import CodeVisualizationService

logger = EnhancedLogger(__name__)


@dataclass
class VisualizeGraphResult:
    """Result from a visualize_graph tool invocation."""

    success: bool
    html_path: Optional[str] = None
    node_count: Optional[int] = None
    edge_count: Optional[int] = None
    error: Optional[str] = None


class VisualizeGraphTool:
    """Tool for generating interactive graph visualizations.

    This tool generates interactive HTML visualizations of code structure,
    including architecture, call graphs, dependencies, hotspots, and call chains.
    """

    SCHEMA = {
        "name": "visualize_graph",
        "description": "Generate an interactive graph visualization of code structure. Supports multiple visualization types: architecture (modules/files), calls (function calls), dependencies (imports), hotspots (highly connected symbols), and call_chain (trace from specific symbol).",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_id": {
                    "type": "string",
                    "description": "The unique identifier of the repository.",
                },
                "viz_type": {
                    "type": "string",
                    "enum": ["architecture", "calls", "dependencies", "hotspots", "call_chain"],
                    "description": "Type of visualization: 'architecture' (high-level structure), 'calls' (function calls), 'dependencies' (file imports), 'hotspots' (most connected symbols), 'call_chain' (trace from symbol).",
                },
                "folder_path": {
                    "type": "string",
                    "description": "Optional folder path to scope the visualization (e.g., 'src/payments').",
                },
                "symbol_name": {
                    "type": "string",
                    "description": "Symbol name for call_chain visualization (required for call_chain type).",
                },
                "direction": {
                    "type": "string",
                    "enum": ["outgoing", "incoming"],
                    "description": "Direction for call_chain: 'outgoing' (what this calls) or 'incoming' (what calls this). Default: 'outgoing'.",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum traversal depth for call_chain (default: 15).",
                },
            },
            "required": ["repo_id", "viz_type"],
        },
    }

    def __init__(self, visualization_service: CodeVisualizationService):
        """Initialize the VisualizeGraphTool.

        Args:
            visualization_service: The CodeVisualizationService for generating visualizations.
        """
        self._service = visualization_service

    def invoke(
        self,
        repo_id: str,
        viz_type: str,
        folder_path: Optional[str] = None,
        symbol_name: Optional[str] = None,
        direction: str = "outgoing",
        max_depth: Optional[int] = None,
    ) -> VisualizeGraphResult:
        """Invoke the visualize_graph tool.

        Args:
            repo_id: The repository ID.
            viz_type: Type of visualization to generate.
            folder_path: Optional folder path to scope the visualization.
            symbol_name: Symbol name for call_chain visualization.
            direction: Direction for call_chain ("outgoing" or "incoming").
            max_depth: Maximum traversal depth for call_chain.

        Returns:
            VisualizeGraphResult containing file path or error.
        """
        # Validate viz_type
        valid_types = ["architecture", "calls", "dependencies", "hotspots", "call_chain"]
        if viz_type not in valid_types:
            return VisualizeGraphResult(
                success=False,
                error=f"Invalid viz_type '{viz_type}'. Must be one of: {valid_types}",
            )

        # Validate call_chain requirements
        if viz_type == "call_chain" and not symbol_name:
            return VisualizeGraphResult(
                success=False,
                error="symbol_name is required for call_chain visualization.",
            )

        try:
            # Convert string to VisualizationType enum
            viz_type_enum = VisualizationType(viz_type)

            # Generate visualization and save to file
            result = self._service.generate_visualization_file(
                repo_id=repo_id,
                viz_type=viz_type_enum,
                folder_path=folder_path,
                symbol_name=symbol_name,
                direction=direction,
                max_depth=max_depth,
            )

            if not result.success:
                return VisualizeGraphResult(
                    success=False,
                    error=result.error,
                )

            return VisualizeGraphResult(
                success=True,
                html_path=result.html,
                node_count=result.node_count,
                edge_count=result.edge_count,
            )

        except ValueError as e:
            logger.error(f"Invalid visualization type: {e}")
            return VisualizeGraphResult(
                success=False,
                error=f"Invalid visualization type: {str(e)}",
            )
        except Exception as e:
            logger.error(f"Failed to generate visualization: {e}", exc_info=True)
            return VisualizeGraphResult(
                success=False,
                error=f"Failed to generate visualization: {str(e)}",
            )

    def format_for_display(self, result: VisualizeGraphResult) -> str:
        """Format result for display to user.

        Args:
            result: The visualization result.

        Returns:
            Formatted string for display.
        """
        if not result.success:
            return f"❌ Visualization failed: {result.error}"

        output = ["✅ Visualization generated successfully!"]
        output.append(f"📊 Nodes: {result.node_count}, Edges: {result.edge_count}")
        output.append(f"📁 Saved to: `{result.html_path}`")
        output.append("\nOpen the HTML file in your browser to explore the interactive visualization.")

        return "\n".join(output)
