"""
Retrieval router.

Provides endpoints for hybrid code retrieval.
"""

import time

from fastapi import APIRouter, Depends, HTTPException

from graph_kb_api.dependencies import get_retrieval_service
from graph_kb_api.schemas.retrieval import (
    ContextItemResponse,
    RetrieveRequest,
    RetrieveResponse,
)

router = APIRouter(tags=["Search"])


@router.post("/repos/{repo_id}/retrieve", response_model=RetrieveResponse)
async def retrieve_context(
    repo_id: str,
    request: RetrieveRequest,
    retrieval_service = Depends(get_retrieval_service),
):
    """
    Full hybrid retrieval with vector search and graph expansion.

    This provides comprehensive context by:
    1. Vector search for semantically similar code
    2. Graph expansion to find related symbols
    3. Location-based scoring for relevance
    """
    try:
        start_time = time.time()

        # Build anchors if provided
        anchors = None
        if request.current_file or request.error_stack:
            from graph_kb_api.graph_kb.models.base import Anchors
            anchors = Anchors(
                current_file=request.current_file,
                error_stack=request.error_stack,
            )

        # Perform hybrid retrieval
        result = retrieval_service.retrieve(
            repo_id=repo_id,
            query=request.query,
            top_k=request.top_k,
            max_depth=request.max_depth,
            anchors=anchors,
        )

        total_duration = time.time() - start_time

        # Extract items from result
        items = []
        if hasattr(result, 'context_items'):
            for item in result.context_items:
                items.append(ContextItemResponse(
                    id=getattr(item, 'id', str(len(items))),
                    file_path=item.file_path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    content=item.content,
                    symbol=getattr(item, 'symbol', None),
                    score=getattr(item, 'score', 0.0),
                    source=getattr(item, 'source', 'hybrid'),
                ))

        return RetrieveResponse(
            items=items,
            total_found=len(items),
            vector_search_duration=getattr(result, 'vector_search_duration', total_duration),
            graph_expansion_duration=getattr(result, 'graph_expansion_duration', None),
            visualization=getattr(result, 'visualization', None),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Retrieval failed: {e}")
