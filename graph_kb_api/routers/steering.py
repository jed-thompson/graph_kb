"""
Steering document management router.

Provides endpoints for listing, retrieving, uploading, updating,
and deleting steering documents that influence LLM behavior.
"""

import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile

from graph_kb_api.core.steering_manager import SteeringManager
from graph_kb_api.schemas.steering import SteeringDocResponse, SteeringListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/steering", tags=["Steering"])


@lru_cache()
def _get_steering_manager() -> SteeringManager:
    """Return a singleton SteeringManager instance."""
    steering_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "core", "steering"
    )
    return SteeringManager(steering_dir)


def _doc_created_at(manager: SteeringManager, filename: str) -> str:
    """Return the file mtime as an ISO timestamp."""
    path = os.path.join(manager.steering_dir, filename)
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    except OSError:
        return datetime.now(timezone.utc).isoformat()


@router.get("", response_model=SteeringListResponse)
async def list_steering_docs(
    manager: SteeringManager = Depends(_get_steering_manager),
):
    """Return all steering documents with total count."""
    try:
        filenames = manager.list_steering_docs()
        documents = []
        for fname in filenames:
            content = manager.read_steering_doc(fname)
            documents.append(
                SteeringDocResponse(
                    filename=fname,
                    content=content or "",
                    created_at=_doc_created_at(manager, fname),
                )
            )
        return SteeringListResponse(documents=documents, total=len(documents))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list steering documents: {e}"
        )


@router.post("", response_model=SteeringDocResponse)
async def add_steering_doc(
    file: UploadFile,
    manager: SteeringManager = Depends(_get_steering_manager),
):
    """Upload a new steering document."""
    try:
        filename = file.filename or "untitled.md"
        content_bytes = await file.read()
        saved_name = manager.save_steering_doc(filename, content_bytes)
        content = manager.read_steering_doc(saved_name) or ""
        return SteeringDocResponse(
            filename=saved_name,
            content=content,
            created_at=_doc_created_at(manager, saved_name),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to upload steering document: {e}"
        )


@router.get("/{filename}", response_model=SteeringDocResponse)
async def get_steering_doc(
    filename: str,
    manager: SteeringManager = Depends(_get_steering_manager),
):
    """Get a single steering document by filename."""
    content = manager.read_steering_doc(filename)
    if content is None:
        raise HTTPException(
            status_code=404, detail=f"Steering document '{filename}' not found"
        )
    return SteeringDocResponse(
        filename=filename,
        content=content,
        created_at=_doc_created_at(manager, filename),
    )


@router.put("/{filename}", response_model=SteeringDocResponse)
async def update_steering_doc(
    filename: str,
    content: str = Body(..., media_type="text/plain"),
    manager: SteeringManager = Depends(_get_steering_manager),
):
    """Update the content of an existing steering document."""
    existing = manager.read_steering_doc(filename)
    if existing is None:
        raise HTTPException(
            status_code=404, detail=f"Steering document '{filename}' not found"
        )
    try:
        manager.save_steering_doc(filename, content.encode("utf-8"))
        updated_content = manager.read_steering_doc(filename) or content
        return SteeringDocResponse(
            filename=filename,
            content=updated_content,
            created_at=_doc_created_at(manager, filename),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to update steering document: {e}"
        )


@router.delete("/{filename}", status_code=204)
async def delete_steering_doc(
    filename: str,
    manager: SteeringManager = Depends(_get_steering_manager),
):
    """Delete a steering document."""
    deleted = manager.delete_steering_doc(filename)
    if not deleted:
        raise HTTPException(
            status_code=404, detail=f"Steering document '{filename}' not found"
        )
    return None
