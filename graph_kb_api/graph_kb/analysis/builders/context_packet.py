"""Context packet builder for Graph RAG operations (V2).

This module builds structured text summaries from graph neighborhoods,
organizing content hierarchically for embedding and RAG pipelines.
Uses neo4j-graphrag patterns for traversal results.
"""

import hashlib
from typing import Dict, List, Optional, Set

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ...models.base import GraphNode
from ...models.enums import GraphNodeType
from ...querying.models import ContextPacket, TraversalEdge, TraversalResult
from ...querying.traversal_utils import EdgeGrouper

logger = EnhancedLogger(__name__)


class ContextPacketBuilderV2:
    """Builds structured text summaries from graph neighborhoods.

    Context packets organize information hierarchically from a root symbol,
    including its relationships and dependencies, suitable for embedding.

    This V2 implementation is designed to work with neo4j-graphrag
    traversal results and patterns.
    """

    def build_packet(
        self,
        traversal_result: TraversalResult,
        root_symbol: str,
    ) -> ContextPacket:
        """Build a context packet from a traversal result.

        Organizes content hierarchically from the root symbol, including
        sections for Calls, Called by, Imports, and Extends relationships.

        Args:
            traversal_result: The result of a graph traversal.
            root_symbol: The ID of the root symbol for this packet.

        Returns:
            A ContextPacket with structured content for embedding.
        """
        # Build hierarchical content
        content = self.build_hierarchical_content(
            nodes=traversal_result.nodes,
            edges=traversal_result.edges,
            root_id=root_symbol,
        )

        # Extract symbols included (names from nodes)
        symbols_included = self._extract_symbols_included(traversal_result.nodes)

        # Extract relationships described
        relationships_described = self._extract_relationship_descriptions(
            traversal_result.edges
        )

        # Generate deterministic packet ID based on content hash
        packet_id = self._generate_packet_id(root_symbol, traversal_result)

        return ContextPacket(
            packet_id=packet_id,
            root_symbol=root_symbol,
            content=content,
            node_count=len(traversal_result.nodes),
            depth=traversal_result.depth_reached,
            symbols_included=symbols_included,
            relationships_described=relationships_described,
        )

    def build_hierarchical_content(
        self,
        nodes: List[GraphNode],
        edges: List[TraversalEdge],
        root_id: str,
    ) -> str:
        """Build hierarchical text content from nodes and edges.

        Organizes content with sections for:
        - Root symbol information (name, type, file path, docstring, summary)
        - Calls (outgoing CALLS edges)
        - Called by (incoming CALLS edges)
        - Imports (outgoing IMPORTS edges)
        - Extends (outgoing EXTENDS edges)

        Args:
            nodes: List of graph nodes.
            edges: List of traversal edges.
            root_id: The ID of the root node.

        Returns:
            Formatted text content suitable for embedding.
        """
        # Build node lookup
        node_map: Dict[str, GraphNode] = {node.id: node for node in nodes}

        # Find root node
        root_node = node_map.get(root_id)

        # Build edge index for quick lookup using EdgeGrouper utility
        outgoing_edges, incoming_edges = EdgeGrouper.group_edges_by_direction(edges)

        # Build content sections
        content_parts: List[str] = []

        # 1. Root symbol section
        if root_node:
            content_parts.append(self._format_symbol_section(root_node))

        # 2. Calls section (outgoing CALLS edges from root)
        calls_section = self._build_calls_section(
            root_id, outgoing_edges, node_map
        )
        if calls_section:
            content_parts.append(calls_section)

        # 3. Called by section (incoming CALLS edges to root)
        called_by_section = self._build_called_by_section(
            root_id, incoming_edges, node_map
        )
        if called_by_section:
            content_parts.append(called_by_section)

        # 4. Imports section (outgoing IMPORTS edges from root)
        imports_section = self._build_imports_section(
            root_id, outgoing_edges, node_map
        )
        if imports_section:
            content_parts.append(imports_section)

        # 5. Extends section (outgoing EXTENDS edges from root)
        extends_section = self._build_extends_section(
            root_id, outgoing_edges, node_map
        )
        if extends_section:
            content_parts.append(extends_section)

        return "\n\n".join(content_parts)

    def _format_symbol_section(self, node: GraphNode) -> str:
        """Format a symbol node as a text section.

        Includes symbol name, type, file path, docstring, and summary.

        Args:
            node: The graph node to format.

        Returns:
            Formatted text section for the symbol.
        """
        attrs = node.attrs
        name = attrs.get("name", node.id)
        symbol_type = self._get_symbol_type(node)

        lines = [f"=== Symbol: {name} ({symbol_type}) ==="]

        # File path and line numbers
        file_path = attrs.get("file_path", "")
        start_line = attrs.get("start_line")

        if file_path:
            if start_line is not None:
                lines.append(f"File: {file_path}:{start_line}")
            else:
                lines.append(f"File: {file_path}")

        # Docstring
        docstring = attrs.get("docstring", "")
        if docstring:
            lines.append(f"Doc: {docstring}")

        # Summary
        if node.summary:
            lines.append(f"Summary: {node.summary}")

        # Visibility
        visibility = attrs.get("visibility", "")
        if visibility:
            lines.append(f"Visibility: {visibility}")

        return "\n".join(lines)

    def _build_calls_section(
        self,
        root_id: str,
        outgoing_edges: Dict[str, List[TraversalEdge]],
        node_map: Dict[str, GraphNode],
    ) -> Optional[str]:
        """Build the 'Calls' section showing functions called by root.

        Args:
            root_id: ID of the root node.
            outgoing_edges: Map of source_id to outgoing edges.
            node_map: Map of node_id to GraphNode.

        Returns:
            Formatted 'Calls' section or None if no calls.
        """
        # Filter outgoing CALLS edges from root
        calls_edges = [
            e for e in outgoing_edges.get(root_id, [])
            if e.edge_type == "CALLS"
        ]

        if not calls_edges:
            return None

        lines = ["Calls:"]
        for edge in calls_edges:
            target_node = node_map.get(edge.target_id)
            if target_node:
                desc = self._format_relationship_target(target_node)
                lines.append(f"  → {desc}")

        return "\n".join(lines)

    def _build_called_by_section(
        self,
        root_id: str,
        incoming_edges: Dict[str, List[TraversalEdge]],
        node_map: Dict[str, GraphNode],
    ) -> Optional[str]:
        """Build the 'Called by' section showing functions that call root.

        Args:
            root_id: ID of the root node.
            incoming_edges: Map of target_id to incoming edges.
            node_map: Map of node_id to GraphNode.

        Returns:
            Formatted 'Called by' section or None if no callers.
        """
        # Filter incoming CALLS edges to root
        called_by_edges = [
            e for e in incoming_edges.get(root_id, [])
            if e.edge_type == "CALLS"
        ]

        if not called_by_edges:
            return None

        lines = ["Called by:"]
        for edge in called_by_edges:
            source_node = node_map.get(edge.source_id)
            if source_node:
                desc = self._format_relationship_target(source_node)
                lines.append(f"  ← {desc}")

        return "\n".join(lines)

    def _build_imports_section(
        self,
        root_id: str,
        outgoing_edges: Dict[str, List[TraversalEdge]],
        node_map: Dict[str, GraphNode],
    ) -> Optional[str]:
        """Build the 'Imports' section showing dependencies.

        Args:
            root_id: ID of the root node.
            outgoing_edges: Map of source_id to outgoing edges.
            node_map: Map of node_id to GraphNode.

        Returns:
            Formatted 'Imports' section or None if no imports.
        """
        imports_edges = [
            e for e in outgoing_edges.get(root_id, [])
            if e.edge_type == "IMPORTS"
        ]

        if not imports_edges:
            return None

        lines = ["Imports:"]
        for edge in imports_edges:
            target_node = node_map.get(edge.target_id)
            if target_node:
                desc = self._format_relationship_target(target_node)
                lines.append(f"  → {desc}")

        return "\n".join(lines)

    def _build_extends_section(
        self,
        root_id: str,
        outgoing_edges: Dict[str, List[TraversalEdge]],
        node_map: Dict[str, GraphNode],
    ) -> Optional[str]:
        """Build the 'Extends' section showing inheritance.

        Args:
            root_id: ID of the root node.
            outgoing_edges: Map of source_id to outgoing edges.
            node_map: Map of node_id to GraphNode.

        Returns:
            Formatted 'Extends' section or None if no inheritance.
        """
        extends_edges = [
            e for e in outgoing_edges.get(root_id, [])
            if e.edge_type == "EXTENDS"
        ]

        if not extends_edges:
            return None

        lines = ["Extends:"]
        for edge in extends_edges:
            target_node = node_map.get(edge.target_id)
            if target_node:
                desc = self._format_relationship_target(target_node)
                lines.append(f"  → {desc}")

        return "\n".join(lines)

    def _format_relationship_target(self, node: GraphNode) -> str:
        """Format a node as a relationship target description.

        Args:
            node: The target node to format.

        Returns:
            Formatted description string.
        """
        attrs = node.attrs
        name = attrs.get("name", node.id)
        symbol_type = self._get_symbol_type(node)

        # Get a brief description
        docstring = attrs.get("docstring", "")
        summary = node.summary or ""

        description = ""
        if docstring:
            # Take first sentence or first 80 chars
            first_sentence = docstring.split(".")[0]
            description = first_sentence[:80] if len(first_sentence) > 80 else first_sentence
        elif summary:
            description = summary[:80] if len(summary) > 80 else summary

        if description:
            return f"{name} ({symbol_type}) - {description}"
        return f"{name} ({symbol_type})"

    def _get_symbol_type(self, node: GraphNode) -> str:
        """Get a human-readable symbol type from a node.

        Args:
            node: The graph node.

        Returns:
            Human-readable symbol type string.
        """
        # First check attrs for kind
        kind = node.attrs.get("kind", "")
        if kind:
            return kind.lower()

        # Fall back to node type
        if node.type == GraphNodeType.SYMBOL:
            return "symbol"
        elif node.type == GraphNodeType.FILE:
            return "file"
        elif node.type == GraphNodeType.DIRECTORY:
            return "directory"
        elif node.type == GraphNodeType.REPO:
            return "repository"

        return "unknown"

    def _extract_symbols_included(self, nodes: List[GraphNode]) -> List[str]:
        """Extract symbol names from nodes.

        Args:
            nodes: List of graph nodes.

        Returns:
            List of symbol names.
        """
        symbols = []
        for node in nodes:
            name = node.attrs.get("name", node.id)
            symbols.append(name)
        return symbols

    def _extract_relationship_descriptions(
        self,
        edges: List[TraversalEdge],
    ) -> List[str]:
        """Extract unique relationship type descriptions from edges.

        Args:
            edges: List of traversal edges.

        Returns:
            Sorted list of unique relationship types.
        """
        relationship_types: Set[str] = set()
        for edge in edges:
            relationship_types.add(edge.edge_type)
        return sorted(list(relationship_types))

    def _generate_packet_id(
        self,
        root_symbol: str,
        traversal_result: TraversalResult,
    ) -> str:
        """Generate a unique packet ID based on content hash.

        The packet ID is deterministic - identical inputs will produce
        identical packet IDs.

        Args:
            root_symbol: The root symbol ID.
            traversal_result: The traversal result.

        Returns:
            A 16-character hex string packet ID.
        """
        # Create a hash from root symbol and sorted node IDs
        node_ids = sorted([node.id for node in traversal_result.nodes])
        content = f"{root_symbol}:{':'.join(node_ids)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
