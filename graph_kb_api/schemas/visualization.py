"""
Pydantic schemas for graph visualization endpoints.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class VisualizationNode(BaseModel):
    """A node in the visualization graph."""

    id: str
    label: str
    type: str
    file_path: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class VisualizationEdge(BaseModel):
    """An edge in the visualization graph."""

    source: str
    target: str
    type: str
    metadata: Optional[Dict[str, Any]] = None


class VisualizationResponse(BaseModel):
    """Visualization response with nodes, edges, and optional HTML."""

    nodes: List[VisualizationNode]
    edges: List[VisualizationEdge]
    html: Optional[str] = None
    viz_type: str
    metadata: Optional[Dict[str, Any]] = None
