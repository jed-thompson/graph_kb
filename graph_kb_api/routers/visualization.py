"""
Visualization router.

Provides an endpoint for generating graph visualizations from indexed
repositories, supporting architecture, calls, dependencies, full,
comprehensive, call_chain, and hotspots visualization types.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.graph_kb.models.visualization import VisualizationType
from graph_kb_api.schemas.visualization import (
    VisualizationEdge,
    VisualizationNode,
    VisualizationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visualize", tags=["Visualization"])

# The set of accepted viz_type path values.
VizTypeLiteral = Literal[
    "architecture",
    "calls",
    "dependencies",
    "full",
    "comprehensive",
    "call_chain",
    "hotspots",
]


@router.get("/repos/{repo_id}/{viz_type}", response_model=VisualizationResponse)
async def get_visualization(
    repo_id: str,
    viz_type: VizTypeLiteral,
    symbol_name: Optional[str] = None,
    direction: str = "outgoing",
    facade=Depends(get_graph_kb_facade),
):
    """Generate a graph visualization for a repository.

    Returns nodes, edges, optional interactive HTML, and the viz_type.
    Returns 404 if the repo_id is not indexed.
    """
    vis_service = facade.visualization_service
    if vis_service is None:
        raise HTTPException(
            status_code=503,
            detail="Visualization service is unavailable",
        )

    try:
        enum_type = VisualizationType(viz_type)
        result = vis_service.generate_visualization(
            repo_id, enum_type, symbol_name=symbol_name, direction=direction
        )
    except Exception as e:
        logger.error("Visualization generation failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate visualization: {e}",
        )

    # The service returns success=False with an error when the repo is
    # not found / not indexed.
    if not result.success and result.error:
        # Treat repository-not-found as 404
        error_lower = result.error.lower()
        if "not found" in error_lower or "not indexed" in error_lower:
            raise HTTPException(status_code=404, detail=result.error)
        raise HTTPException(status_code=500, detail=result.error)

    # Build the internal VisGraph so we can extract nodes/edges.
    # Re-query the graph to get the raw node/edge data (the result only
    # carries HTML + counts).  We call _query_graph which is the same
    # path generate_visualization uses internally.
    try:
        graph = vis_service._query_graph(repo_id, enum_type, symbol_name=symbol_name, direction=direction)
    except Exception:
        # If re-querying fails, return the HTML-only response.
        graph = None

    nodes = []
    edges = []

    if graph and graph.nodes:
        for n in graph.nodes:
            nodes.append(
                VisualizationNode(
                    id=n.id,
                    label=n.label,
                    type=n.node_type.value,
                    file_path=n.full_path or None,
                    metadata=n.metadata or None,
                )
            )

        valid_node_ids = {n.id for n in nodes}

        if graph.edges:
            for e in graph.edges:
                # Ensure edge source/target reference valid node IDs
                if e.source in valid_node_ids and e.target in valid_node_ids:
                    edges.append(
                        VisualizationEdge(
                            source=e.source,
                            target=e.target,
                            type=e.edge_type.value,
                            metadata=None,
                        )
                    )

    return VisualizationResponse(
        nodes=nodes,
        edges=edges,
        html=result.html,
        viz_type=viz_type,
        metadata=None,
    )
