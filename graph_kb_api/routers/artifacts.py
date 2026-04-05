"""
Chat artifact storage router.

Provides an endpoint for saving assistant chat responses as markdown
artifacts in blob storage.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from graph_kb_api.storage.blob_storage import BlobStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])


class SaveChatArtifactRequest(BaseModel):
    content: str
    filename: str
    message_id: str | None = None


class SaveChatArtifactResponse(BaseModel):
    path: str
    message: str


@router.post("/chat", response_model=SaveChatArtifactResponse)
async def save_chat_artifact(request: SaveChatArtifactRequest) -> SaveChatArtifactResponse:
    """Save a chat assistant response as a markdown artifact in blob storage."""
    try:
        storage = BlobStorage.from_env()
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

        safe_name = request.filename.replace("/", "_").replace("..", "").strip()
        if not safe_name:
            safe_name = "response"
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        path = f"chat/{timestamp}_{safe_name}"
        stored_path = await storage.backend.store(
            path,
            request.content,
            "text/markdown",
            metadata={
                "message_id": request.message_id or "",
                "filename": safe_name,
                "stored_at": datetime.now(UTC).isoformat(),
                "source": "chat",
            },
        )
        return SaveChatArtifactResponse(path=stored_path, message="Artifact saved successfully")
    except Exception as e:
        logger.error("Failed to save chat artifact: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
