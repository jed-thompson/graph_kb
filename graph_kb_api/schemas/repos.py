"""
Repository Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class RepoStatus(str, Enum):
    """Repository indexing status."""

    PENDING = "pending"
    CLONING = "cloning"
    INDEXING = "indexing"
    PAUSED = "paused"
    READY = "ready"
    ERROR = "error"


class RepoResponse(BaseModel):
    """Repository details response."""

    id: str
    git_url: str
    branch: str
    status: RepoStatus
    last_indexed_at: Optional[datetime] = None
    commit_sha: Optional[str] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class RepoListResponse(BaseModel):
    """List of repositories response."""

    repos: list[RepoResponse]
    total: int
    offset: int = 0
    limit: int = 50


class RepoCreateRequest(BaseModel):
    """Request to create/ingest a repository."""

    git_url: str
    branch: str = "main"
