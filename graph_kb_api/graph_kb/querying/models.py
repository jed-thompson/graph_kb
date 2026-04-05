"""Query-related data models.

This module contains data models specific to graph querying and traversal operations,
including recursive traversal, Graph RAG, and context building.

Merged from analysis/traversal_models.py during refactoring.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

# Import from other modules
from ..models.base import GraphNode
from ..models.visualization import VisGraph


class QueryType(Enum):
    """Types of graph queries."""
    SYMBOL_LOOKUP = "symbol_lookup"
    PATH_FINDING = "path_finding"
    NEIGHBORHOOD = "neighborhood"
    TRAVERSAL = "traversal"
    PATTERN_MATCH = "pattern_match"
    ARCHITECTURE = "architecture"
    SIMILARITY = "similarity"


class TraversalDirection(Enum):
    """Direction for graph traversal."""
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


@dataclass
class QueryConfig:
    """Configuration for graph queries."""
    max_depth: int = 5
    max_nodes: int = 1000
    direction: TraversalDirection = TraversalDirection.OUTGOING
    edge_types: List[str] = field(default_factory=list)
    include_metadata: bool = True
    timeout: float = 30.0


@dataclass
class TraversalEdge:
    """An edge discovered during graph traversal.

    Note: Named TraversalEdge to avoid conflict with GraphEdge in models.base
    which has different fields (id, from_node, to_node, edge_type, attrs).
    """
    source_id: str
    target_id: str
    edge_type: str
    direction: str  # "outgoing" or "incoming"
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraversalResult:
    """Result of a recursive graph traversal operation.

    Contains all nodes and edges discovered within the specified depth,
    along with metadata about the traversal.
    """
    nodes: List[GraphNode]
    edges: List[TraversalEdge]
    depth_reached: int
    is_truncated: bool
    node_count_by_depth: Dict[int, int] = field(default_factory=dict)
    traversal_time: float = 0.0
    start_node_id: str = ""


@dataclass
class ContextPacket:
    """A structured text summary of a graph neighborhood for RAG.

    Context packets organize information hierarchically from a root symbol,
    including its relationships and dependencies, suitable for embedding.
    """
    packet_id: str
    root_symbol: str
    content: str  # The text for embedding
    node_count: int
    depth: int
    symbols_included: List[str] = field(default_factory=list)
    relationships_described: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MermaidDiagram:
    """A Mermaid diagram representation of a graph subgraph."""
    code: str
    node_count: int
    edge_count: int
    is_collapsed: bool
    diagram_type: str = "graph"  # graph, flowchart, etc.


@dataclass
class GraphRAGResult:
    """Result of a Graph RAG retrieval operation.

    Contains context packets built from graph neighborhoods,
    optional visualization (either Mermaid or interactive VisGraph),
    and metadata about the retrieval.
    """
    query: str
    context_packets: List[ContextPacket]
    visualization: Optional[MermaidDiagram]
    symbols_found: List[str]
    total_nodes_explored: int
    retrieval_strategy: str
    # Interactive pyvis visualization graph (used by ask_code for HTML rendering)
    vis_graph: Optional[VisGraph] = None
    retrieval_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryResult:
    """Generic result for graph queries."""
    query_type: QueryType
    success: bool
    results: List[Any]
    total_results: int
    execution_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class PathResult:
    """Result of path finding between nodes."""
    start_node_id: str
    end_node_id: str
    path_nodes: List[str]
    path_length: int
    path_exists: bool
    total_paths_found: int = 1


@dataclass
class NeighborhoodResult:
    """Result of neighborhood exploration."""
    center_node_id: str
    neighbors: List[GraphNode]
    relationships: List[TraversalEdge]
    depth_explored: int
    total_neighbors: int


@dataclass
class SymbolMatch:
    """A symbol matching a search pattern."""
    id: str
    name: str
    kind: str
    file_path: str
    line_number: int
    docstring: Optional[str] = None
    confidence: float = 1.0


@dataclass
class PatternMatchResult:
    """Result of pattern matching query."""
    pattern: str
    matches: List[SymbolMatch]
    total_matches: int
    match_time: float


@dataclass
class ArchitectureQuery:
    """Query for architecture overview."""
    repo_id: str
    include_modules: bool = True
    include_relationships: bool = True
    max_depth: int = 3
    filter_patterns: List[str] = field(default_factory=list)


@dataclass
class ArchitectureResult:
    """Result of architecture query."""
    repo_id: str
    modules: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    entry_points: List[Dict[str, Any]]
    statistics: Dict[str, Any] = field(default_factory=dict)
