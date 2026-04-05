"""
Analysis router.

Provides endpoints for code analysis operations.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from graph_kb_api.dependencies import get_analysis_service, get_graph_kb_facade

router = APIRouter(tags=["Analysis"])


class ArchitectureOverview(BaseModel):
    """Architecture overview response."""

    modules: List[Dict[str, Any]]
    entry_points: List[Dict[str, Any]]
    total_files: int
    total_symbols: int


class EntryPoint(BaseModel):
    """Entry point response."""

    symbol_id: str
    name: str
    file_path: str
    type: str  # "function", "class", "endpoint"
    description: str = ""
    score: float = 0.0


class HotspotAnalysis(BaseModel):
    """Code hotspot response."""

    file_path: str
    symbol_name: str
    complexity: int
    incoming_calls: int
    outgoing_calls: int
    change_frequency: int = 0


class GraphStats(BaseModel):
    """Graph statistics response."""

    total_nodes: int
    total_edges: int
    node_counts: Dict[str, int]
    edge_counts: Dict[str, int]
    depth_analysis: Dict[str, int] = {}
    symbol_kinds: Dict[str, int] = {}


@router.get("/repos/{repo_id}/architecture", response_model=ArchitectureOverview)
async def get_architecture(
    repo_id: str,
    analysis_service=Depends(get_analysis_service),
):
    """
    Get an architecture overview of the repository.

    Returns high-level module structure and key entry points.
    """
    try:
        overview = analysis_service.get_architecture(repo_id)

        return ArchitectureOverview(
            modules=getattr(overview, "modules", []),
            entry_points=getattr(overview, "entry_points", []),
            total_files=getattr(overview, "total_files", 0),
            total_symbols=getattr(overview, "total_symbols", 0),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get architecture: {e}")


@router.get("/repos/{repo_id}/entry-points", response_model=List[EntryPoint])
async def get_entry_points(
    repo_id: str,
    limit: int = 20,
    analysis_service=Depends(get_analysis_service),
):
    """
    List the main entry points in the repository.

    Entry points include main functions, API endpoints, CLI commands, etc.
    """
    try:
        entry_points = analysis_service.analyze_entry_points(repo_id)

        return [
            EntryPoint(
                symbol_id=ep.id if hasattr(ep, "id") else str(i),
                name=ep.name,
                file_path=ep.file_path,
                type=ep.entry_type.value
                if hasattr(ep.entry_type, "value")
                else str(ep.entry_type),
                description=getattr(ep, "description", "") or "",
            )
            for i, ep in enumerate(entry_points[:limit])
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get entry points: {e}")


@router.get("/repos/{repo_id}/hotspots", response_model=List[HotspotAnalysis])
async def get_hotspots(
    repo_id: str,
    limit: int = 20,
    facade=Depends(get_graph_kb_facade),
):
    """
    Identify code hotspots in the repository.

    Hotspots are areas with high complexity or high change frequency.
    """
    try:
        vis_service = facade.visualization_service
        if not vis_service:
            return []

        vis_graph = vis_service.get_hotspots(repo_id=repo_id, top_n=limit)

        return [
            HotspotAnalysis(
                file_path=node.full_path or "unknown",
                symbol_name=node.label,
                complexity=node.metadata.get("total_connections", 0),
                incoming_calls=node.metadata.get("incoming_calls", 0),
                outgoing_calls=node.metadata.get("outgoing_calls", 0),
                change_frequency=0,
            )
            for node in vis_graph.nodes
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to analyze hotspots: {e}")


@router.get("/repos/{repo_id}/stats", response_model=GraphStats)
async def get_stats(
    repo_id: str,
    facade=Depends(get_graph_kb_facade),
):
    """
    Get graph statistics for the repository.

    Returns counts of nodes and edges by type.
    """
    try:
        stats_adapter = facade.stats_adapter
        if not stats_adapter:
            return GraphStats(
                total_nodes=0,
                total_edges=0,
                node_counts={},
                edge_counts={},
            )

        stats = stats_adapter.get_stats(repo_id)

        # Merge symbol_kinds (function, class, method, etc.) into node_counts
        # so the dashboard can access counts like node_counts['function']
        merged_counts = dict(stats.node_counts)
        if stats.symbol_kinds:
            merged_counts.update(stats.symbol_kinds)

        return GraphStats(
            total_nodes=stats.total_nodes,
            total_edges=stats.total_edges,
            node_counts=merged_counts,
            edge_counts=stats.edge_counts,
            depth_analysis=stats.depth_analysis or {},
            symbol_kinds=stats.symbol_kinds or {},
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}")
