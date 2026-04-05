"""GraphRenderer for pyvis HTML generation.

This module provides the GraphRenderer class that transforms VisGraph data
into interactive HTML visualizations using pyvis.
"""

import os
from typing import Dict

from pyvis.network import Network

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..models.enums import GraphEdgeType, GraphNodeType
from ..models.visualization import VisGraph, VisNode

logger = EnhancedLogger(__name__)


class GraphRenderer:
    """Renders VisGraph to interactive HTML using pyvis."""

    # Node colors by GraphNodeType
    NODE_COLORS: Dict[GraphNodeType, str] = {
        GraphNodeType.REPO: "#8B5CF6",      # Purple - repository root
        GraphNodeType.DIRECTORY: "#3B82F6",  # Blue - directories
        GraphNodeType.FILE: "#22C55E",       # Green - files
        GraphNodeType.SYMBOL: "#F97316",     # Orange - symbols
    }

    # Edge colors by GraphEdgeType
    EDGE_COLORS: Dict[GraphEdgeType, str] = {
        GraphEdgeType.CONTAINS: "#9CA3AF",    # Gray - containment
        GraphEdgeType.CALLS: "#EF4444",       # Red - function calls
        GraphEdgeType.IMPORTS: "#3B82F6",     # Blue - imports
        GraphEdgeType.IMPLEMENTS: "#10B981",  # Emerald - implements
        GraphEdgeType.EXTENDS: "#F59E0B",     # Amber - extends
        GraphEdgeType.REPRESENTED_BY: "#D1D5DB",  # Light gray
        GraphEdgeType.USES: "#8B5CF6",        # Purple - variable references
        GraphEdgeType.DECORATES: "#EC4899",   # Pink - decorators
        GraphEdgeType.NEXT_CHUNK: "#CBD5E1",  # Slate - chunk ordering
    }

    # Node shapes by type for visual distinction
    NODE_SHAPES: Dict[GraphNodeType, str] = {
        GraphNodeType.REPO: "database",
        GraphNodeType.DIRECTORY: "box",
        GraphNodeType.FILE: "dot",
        GraphNodeType.SYMBOL: "diamond",
    }

    def __init__(self, height: str = "calc(100vh - 100px)", width: str = "100%"):
        """Initialize the GraphRenderer.

        Args:
            height: Height of the visualization (CSS value). Defaults to viewport height minus padding.
            width: Width of the visualization (CSS value).
        """
        self.height = height
        self.width = width

    def render(self, graph: VisGraph, title: str = "Graph Visualization", show_legend: bool = True) -> str:
        """Render VisGraph to HTML string using pyvis.

        Creates a pyvis Network, adds nodes and edges with appropriate
        styling, and returns the HTML string.

        Args:
            graph: The VisGraph to render.
            title: Title for the visualization.
            show_legend: Whether to include a color legend.

        Returns:
            Complete HTML string that can be saved to a file.
        """
        # Create pyvis network (no heading to avoid duplicate title)
        net = Network(
            height=self.height,
            width=self.width,
            directed=True,
            notebook=False,
        )

        # Configure physics and interaction options
        net.set_options("""
        {
            "physics": {
                "enabled": true,
                "solver": "forceAtlas2Based",
                "forceAtlas2Based": {
                    "gravitationalConstant": -50,
                    "centralGravity": 0.01,
                    "springLength": 100,
                    "springConstant": 0.08
                },
                "stabilization": {
                    "enabled": true,
                    "iterations": 200
                }
            },
            "interaction": {
                "hover": true,
                "tooltipDelay": 100,
                "zoomView": true,
                "dragView": true,
                "navigationButtons": true
            },
            "nodes": {
                "font": {
                    "size": 12
                }
            },
            "edges": {
                "smooth": {
                    "type": "continuous"
                },
                "arrows": {
                    "to": {
                        "enabled": true,
                        "scaleFactor": 0.5
                    }
                }
            }
        }
        """)

        # Add nodes
        for node in graph.nodes:
            color = self.NODE_COLORS.get(node.node_type, "#6B7280")
            shape = self.NODE_SHAPES.get(node.node_type, "dot")
            title = self._build_hover_title(node)
            label = node.truncated_label(30)

            net.add_node(
                node.id,
                label=label,
                title=title,
                color=color,
                shape=shape,
                size=20 if node.node_type == GraphNodeType.DIRECTORY else 15,
            )

        # Add edges
        for edge in graph.edges:
            color = self.EDGE_COLORS.get(edge.edge_type, "#9CA3AF")

            net.add_edge(
                edge.source,
                edge.target,
                color=color,
                title=edge.edge_type.value,
                label=edge.label if edge.label else "",
            )

        # Generate HTML
        html = net.generate_html()

        # Make the graph container responsive (replace fixed heights with viewport-based)
        html = self._make_responsive(html)

        # Inject legend if requested
        if show_legend:
            html = self._inject_legend(html, graph, title)

        return html

    def _make_responsive(self, html: str) -> str:
        """Make the graph container responsive by replacing fixed heights with viewport-based heights.

        Args:
            html: The generated HTML string.

        Returns:
            HTML with responsive heights.
        """
        # Extract the height value (could be "750px", "calc(100vh - 100px)", etc.)
        # Convert to a numeric value for calculations if needed
        height_value = self.height

        # Replace fixed pixel heights in the mynetwork container and loading bar
        # Pattern: height: 750px -> height: calc(100vh - 100px)
        import re

        # Replace height in #mynetwork style
        html = re.sub(
            r'(#mynetwork\s*\{[^}]*height:\s*)\d+px',
            rf'\1{height_value}',
            html,
            flags=re.DOTALL
        )

        # Replace height in #loadingBar style
        html = re.sub(
            r'(#loadingBar\s*\{[^}]*height:\s*)\d+px',
            rf'\1{height_value}',
            html,
            flags=re.DOTALL
        )

        # Also ensure the container uses the responsive height
        # Replace any remaining fixed heights in style blocks
        html = re.sub(
            r'height:\s*750px',
            f'height: {height_value}',
            html
        )

        return html

    def _inject_legend(self, html: str, graph: VisGraph, title: str = "Graph Visualization") -> str:
        """Inject a color legend into the HTML visualization.

        Args:
            html: The generated HTML string.
            graph: The VisGraph to extract used types from.
            title: Title for the visualization.

        Returns:
            HTML with legend injected.
        """
        # Collect used node and edge types
        used_node_types = {node.node_type for node in graph.nodes}
        used_edge_types = {edge.edge_type for edge in graph.edges}

        # Truncate title if it's too long (e.g., if it contains newlines or is very long)
        display_title = title
        if '\n' in display_title:
            # If title has newlines, take just the first line
            display_title = display_title.split('\n')[0]
        if len(display_title) > 50:
            # Truncate very long titles
            display_title = display_title[:47] + "..."

        # Build legend HTML
        legend_items = []

        # Node legend
        legend_items.append('<div style="margin-bottom: 10px;"><strong>Nodes:</strong></div>')
        for node_type in sorted(used_node_types, key=lambda x: x.value):
            color = self.NODE_COLORS.get(node_type, "#6B7280")
            shape_icon = "●" if node_type == GraphNodeType.FILE else "■" if node_type == GraphNodeType.DIRECTORY else "◆" if node_type == GraphNodeType.SYMBOL else "⬢"
            legend_items.append(
                f'<div style="margin: 3px 0;"><span style="color: {color}; font-size: 14px;">{shape_icon}</span> {node_type.value}</div>'
            )

        # Edge legend
        legend_items.append('<div style="margin: 15px 0 10px 0;"><strong>Edges:</strong></div>')
        for edge_type in sorted(used_edge_types, key=lambda x: x.value):
            color = self.EDGE_COLORS.get(edge_type, "#9CA3AF")
            legend_items.append(
                f'<div style="margin: 3px 0;"><span style="display: inline-block; width: 30px; height: 3px; background: {color}; vertical-align: middle;"></span> {edge_type.value}</div>'
            )

        legend_html = f'''
        <div id="graph-legend" style="
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 12px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 11px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            z-index: 1000;
            max-height: 80vh;
            overflow-y: auto;
            max-width: 200px;
        ">
            <div style="font-weight: bold; margin-bottom: 8px; font-size: 12px; word-wrap: break-word;">{display_title}</div>
            {''.join(legend_items)}
            <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid #e5e7eb; font-size: 10px; color: #6b7280;">
                Nodes: {len(graph.nodes)} | Edges: {len(graph.edges)}
            </div>
        </div>
        '''

        # Inject before closing body tag
        html = html.replace('</body>', f'{legend_html}</body>')
        return html

    def render_to_file(
        self, graph: VisGraph, title: str, output_path: str
    ) -> str:
        """Render VisGraph to an HTML file.

        Chainlit can serve files via cl.File element. This method saves
        the rendered HTML to a file that can be attached to a message.

        Args:
            graph: The VisGraph to render.
            title: Title for the visualization.
            output_path: Path where HTML file will be saved.

        Returns:
            The output_path for convenience.
        """
        # Ensure directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Generate HTML
        html_content = self.render(graph, title)

        # Write to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        logger.info(f"Rendered visualization to {output_path}")
        return output_path

    def _build_hover_title(self, node: VisNode) -> str:
        """Build hover tooltip with full path and type info.

        Args:
            node: The VisNode to build tooltip for.

        Returns:
            Plain text string for the tooltip.
        """
        lines = [
            node.label,
            f"Type: {node.node_type.value}",
            f"Path: {node.full_path}",
        ]
        if node.symbol_kind:
            lines.append(f"Kind: {node.symbol_kind}")
        return "\n".join(lines)

    def get_node_color(self, node_type: GraphNodeType) -> str:
        """Get the color for a node type.

        Args:
            node_type: The GraphNodeType.

        Returns:
            Hex color string.
        """
        return self.NODE_COLORS.get(node_type, "#6B7280")

    def get_edge_color(self, edge_type: GraphEdgeType) -> str:
        """Get the color for an edge type.

        Args:
            edge_type: The GraphEdgeType.

        Returns:
            Hex color string.
        """
        return self.EDGE_COLORS.get(edge_type, "#9CA3AF")
