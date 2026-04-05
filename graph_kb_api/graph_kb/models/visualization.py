"""Visualization data models.

This module contains data models for graph visualization, including nodes,
edges, complete visualization graphs, visualization types, and results.

Moved from visualization/models.py to break circular dependencies and follow
the architecture pattern where models are in the shared models/ directory.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .base import GraphNode
from .enums import GraphEdgeType, GraphNodeType


class VisualizationType(str, Enum):
    """Types of visualizations that can be generated."""

    ARCHITECTURE = "architecture"  # Directory structure with CONTAINS edges
    CALLS = "calls"  # Symbol nodes with CALLS edges
    DEPENDENCIES = "dependencies"  # File nodes with IMPORTS edges
    FULL = "full"  # All node types and edge types
    COMPREHENSIVE = "comprehensive"  # Single unified graph with all nodes and edges
    CALL_CHAIN = "call_chain"  # Trace calls from/to a specific symbol
    HOTSPOTS = "hotspots"  # Most connected symbols in the codebase


@dataclass
class VisualizationResult:
    """Result of a visualization generation."""

    success: bool
    html: Optional[str] = None
    error: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0


@dataclass
class VisNode:
    """A node in the visualization graph.

    Wraps GraphNode data with visualization-specific attributes.
    """

    id: str
    label: str
    node_type: GraphNodeType
    full_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    symbol_kind: Optional[str] = None

    def truncated_label(self, max_length: int = 30) -> str:
        """Return label truncated with ellipsis if needed."""
        if len(self.label) <= max_length:
            return self.label
        return self.label[: max_length - 3] + "..."

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "node_type": self.node_type.value,
            "full_path": self.full_path,
            "metadata": self.metadata,
            "symbol_kind": self.symbol_kind,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisNode":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            label=data["label"],
            node_type=GraphNodeType(data["node_type"]),
            full_path=data["full_path"],
            metadata=data.get("metadata", {}),
            symbol_kind=data.get("symbol_kind"),
        )

    @classmethod
    def from_graph_node(cls, node: GraphNode) -> "VisNode":
        """Create VisNode from existing GraphNode."""
        attrs = node.attrs or {}
        file_path = attrs.get("file_path", "")
        name = attrs.get("name", file_path.split("/")[-1] if file_path else node.id)
        return cls(
            id=node.id,
            label=name,
            node_type=node.type,
            full_path=file_path,
            metadata=attrs,
            symbol_kind=attrs.get("kind"),
        )


@dataclass
class VisEdge:
    """An edge in the visualization graph.

    Wraps GraphEdge data with visualization-specific attributes.
    """

    source: str
    target: str
    edge_type: GraphEdgeType
    label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type.value,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisEdge":
        """Deserialize from dictionary."""
        return cls(
            source=data["source"],
            target=data["target"],
            edge_type=GraphEdgeType(data["edge_type"]),
            label=data.get("label"),
        )


@dataclass
class VisGraph:
    """Complete visualization graph with nodes and edges."""

    nodes: List[VisNode] = field(default_factory=list)
    edges: List[VisEdge] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisGraph":
        """Deserialize from dictionary."""
        return cls(
            nodes=[VisNode.from_dict(n) for n in data.get("nodes", [])],
            edges=[VisEdge.from_dict(e) for e in data.get("edges", [])],
        )

    def filter_by_path(self, path_prefix: str) -> "VisGraph":
        """Return a new VisGraph containing only nodes within the path prefix."""
        filtered_nodes = [n for n in self.nodes if n.full_path.startswith(path_prefix)]
        node_ids = {n.id for n in filtered_nodes}
        filtered_edges = [
            e for e in self.edges if e.source in node_ids and e.target in node_ids
        ]
        return VisGraph(nodes=filtered_nodes, edges=filtered_edges)
