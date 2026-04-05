"""Graph statistics models."""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class GraphStats:
    """Container for graph statistics."""

    repo_id: str
    node_counts: Dict[str, int] = field(default_factory=dict)
    symbol_kinds: Dict[str, int] = field(default_factory=dict)
    edge_counts: Dict[str, int] = field(default_factory=dict)
    depth_analysis: Dict[str, int] = field(default_factory=dict)
    total_nodes: int = 0
    total_edges: int = 0
    sample_chains: List[Dict] = field(default_factory=list)
