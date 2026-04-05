"""
Sources router.

Provides endpoints for retrieving cached sources from workflow executions.
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["Sources"])


class SourcesResponse(BaseModel):
    """Response model for sources retrieval."""
    workflow_id: str
    sources: List[Dict[str, Any]]
    total_count: int
    repo_id: str
    query: str
    cached_at: float


class SourcesNotFoundResponse(BaseModel):
    """Response model when sources are not found."""
    error: str
    message: str


@router.get("/{workflow_id}", response_model=SourcesResponse, responses={
    404: {"model": SourcesNotFoundResponse, "description": "Sources not found or expired"}
})
async def get_sources(workflow_id: str):
    """
    Retrieve cached sources by workflow ID.

    Sources are cached for 1 hour after workflow completion.
    If the cache entry has expired or doesn't exist, a 404 is returned.

    Args:
        workflow_id: The workflow ID from a previous chat interaction

    Returns:
        SourcesResponse containing all sources and metadata
    """
    from graph_kb_api.flows.v3.utils.sources_cache import sources_cache

    cached = sources_cache.get(workflow_id)

    if cached is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"Sources for workflow '{workflow_id}' not found or expired. Sources are cached for 1 hour."
            }
        )

    return SourcesResponse(
        workflow_id=workflow_id,
        sources=cached.sources,
        total_count=cached.total_count,
        repo_id=cached.repo_id,
        query=cached.query,
        cached_at=cached.created_at,
    )
