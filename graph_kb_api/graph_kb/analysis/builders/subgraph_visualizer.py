"""SubgraphVisualizer V2 for generating Mermaid diagrams from graph traversals.

This module provides the SubgraphVisualizerV2 class that transforms TraversalResult
data into Mermaid flowchart diagrams for visualization.

This is a direct port of the V1 SubgraphVisualizer with identical functionality.
"""

import re
from typing import Dict, List, Optional, Set

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.enums import GraphNodeType
from ...querying.models import MermaidDiagram, TraversalEdge, TraversalResult

logger = EnhancedLogger(__name__)


class SubgraphVisualizerV2:
    """Generates Mermaid diagrams from graph traversal results.

    Transforms TraversalResult into Mermaid flowchart syntax with:
    - Different node shapes for different symbol types (function, class, module)
    - Directional arrows for relationship types
    - Collapsing for large graphs exceeding threshold
    """

    # Node shapes by GraphNodeType for Mermaid syntax
    NODE_SHAPES: Dict[GraphNodeType, tuple] = {
        GraphNodeType.SYMBOL: ("[", "]"),      # Rectangle for symbols (default)
        GraphNodeType.FILE: ("([", "])"),      # Stadium for files
        GraphNodeType.DIRECTORY: ("[(", ")]"), # Cylinder for directories
        GraphNodeType.REPO: ("{{", "}}"),      # Hexagon for repo
    }

    # Symbol kind to shape mapping (more specific than node type)
    SYMBOL_KIND_SHAPES: Dict[str, tuple] = {
        "function": ("[", "]"),       # Rectangle
        "method": ("[", "]"),         # Rectangle
        "class": ("[[", "]]"),        # Subroutine shape
        "interface": ("[[", "]]"),    # Subroutine shape
        "module": ("{{", "}}"),       # Hexagon
        "enum": ("[/", "/]"),         # Parallelogram
        "variable": ("(", ")"),       # Rounded rectangle
        "constant": ("(", ")"),       # Rounded rectangle
    }

    # Edge styles by GraphEdgeType
    EDGE_STYLES: Dict[str, str] = {
        "CALLS": "-->",           # Solid arrow for calls
        "IMPORTS": "-.->",        # Dashed arrow for imports
        "EXTENDS": "===>",        # Thick arrow for extends
        "IMPLEMENTS": "-.->",     # Dashed arrow for implements
        "CONTAINS": "-->",        # Solid arrow for contains
    }

    def __init__(
        self,
        max_nodes: int = 50,
        collapse_threshold: int = 30,
    ):
        """Initialize the SubgraphVisualizerV2.

        Args:
            max_nodes: Maximum nodes to display before truncating.
            collapse_threshold: Node count above which distant nodes are collapsed.
        """
        self.max_nodes = max_nodes
        self.collapse_threshold = collapse_threshold

    def generate_diagram(
        self,
        traversal_result: TraversalResult,
        max_nodes: Optional[int] = None,
        collapse_threshold: Optional[int] = None,
    ) -> MermaidDiagram:
        """Generate a Mermaid flowchart from traversal result.

        Args:
            traversal_result: The TraversalResult containing nodes and edges.
            max_nodes: Override for maximum nodes to display.
            collapse_threshold: Override for collapse threshold.

        Returns:
            MermaidDiagram with the generated code and metadata.
        """
        max_nodes = max_nodes or self.max_nodes
        collapse_threshold = collapse_threshold or self.collapse_threshold

        nodes = traversal_result.nodes
        edges = traversal_result.edges

        # Handle empty graph
        if not nodes:
            return MermaidDiagram(
                code="flowchart TD\n    empty[No nodes to display]",
                node_count=0,
                edge_count=0,
                is_collapsed=False,
            )

        # Determine if we need to collapse
        is_collapsed = len(nodes) > collapse_threshold

        if is_collapsed:
            nodes, edges = self._collapse_graph(
                nodes, edges, max_nodes, traversal_result.node_count_by_depth
            )

        # Build Mermaid code
        lines = ["flowchart TD"]

        # Track node IDs for edge validation
        node_ids: Set[str] = set()

        # Add node definitions
        for node in nodes:
            node_id = self._sanitize_id(node.id)
            node_ids.add(node_id)

            label = self._get_node_label(node)
            shape_start, shape_end = self._get_node_shape(node)

            # Escape special characters in label
            safe_label = self._escape_label(label)

            # If label contains | (line break), wrap in quotes for Mermaid
            if '|' in safe_label:
                safe_label = f'"{safe_label}"'

            lines.append(f"    {node_id}{shape_start}{safe_label}{shape_end}")

        # Add edge definitions
        edge_count = 0
        for edge in edges:
            source_id = self._sanitize_id(edge.source_id)
            target_id = self._sanitize_id(edge.target_id)

            # Only add edge if both nodes exist
            if source_id in node_ids and target_id in node_ids:
                arrow = self._get_edge_style(edge.edge_type)
                edge_label = edge.edge_type
                lines.append(f"    {source_id} {arrow}|{edge_label}| {target_id}")
                edge_count += 1

        code = "\n".join(lines)

        return MermaidDiagram(
            code=code,
            node_count=len(nodes),
            edge_count=edge_count,
            is_collapsed=is_collapsed,
        )

    def _get_node_shape(self, node) -> tuple:
        """Get Mermaid shape delimiters for a node based on its type."""
        attrs = node.attrs or {}
        symbol_kind = attrs.get("kind", "").lower()

        if symbol_kind and symbol_kind in self.SYMBOL_KIND_SHAPES:
            return self.SYMBOL_KIND_SHAPES[symbol_kind]

        return self.NODE_SHAPES.get(node.type, ("[", "]"))

    def _get_edge_style(self, edge_type: str) -> str:
        """Get Mermaid arrow style for an edge type."""
        return self.EDGE_STYLES.get(edge_type.upper(), "-->")

    def _get_node_label(self, node) -> str:
        """Get display label for a node."""
        attrs = node.attrs or {}
        name = attrs.get("name", node.id.split(":")[-1])
        symbol_kind = attrs.get("kind", node.type.value if hasattr(node.type, 'value') else str(node.type))

        if len(name) > 25:
            name = name[:22] + "..."

        return f"{name}|{symbol_kind}"

    def _sanitize_id(self, node_id: str) -> str:
        """Sanitize node ID for Mermaid compatibility."""
        sanitized = re.sub(r'[^a-zA-Z0-9]', '_', node_id)

        if sanitized and not sanitized[0].isalpha():
            sanitized = "n_" + sanitized

        if not sanitized:
            sanitized = "node"

        return sanitized

    def _escape_label(self, label: str) -> str:
        """Escape special characters in Mermaid labels."""
        label = label.replace('"', "'")
        label = label.replace("[", "&#91;")
        label = label.replace("]", "&#93;")
        return label

    def _collapse_graph(
        self,
        nodes: List,
        edges: List[TraversalEdge],
        max_nodes: int,
        node_count_by_depth: Dict[int, int],
    ) -> tuple:
        """Collapse a large graph by keeping only the most important nodes."""
        if len(nodes) <= max_nodes:
            return nodes, edges

        node_edge_count: Dict[str, int] = {}
        for edge in edges:
            node_edge_count[edge.source_id] = node_edge_count.get(edge.source_id, 0) + 1
            node_edge_count[edge.target_id] = node_edge_count.get(edge.target_id, 0) + 1

        sorted_nodes = sorted(
            nodes,
            key=lambda n: node_edge_count.get(n.id, 0),
            reverse=True
        )

        kept_nodes = sorted_nodes[:max_nodes]
        kept_node_ids = {n.id for n in kept_nodes}

        kept_edges = [
            e for e in edges
            if e.source_id in kept_node_ids and e.target_id in kept_node_ids
        ]

        collapsed_count = len(nodes) - len(kept_nodes)

        if collapsed_count > 0:
            logger.info(f"Collapsed {collapsed_count} nodes in visualization")

        return kept_nodes, kept_edges
