"""Pydantic schemas for Plan session REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PlanSessionResponse(BaseModel):
    """Response for a single plan session."""

    id: str
    thread_id: str
    user_id: str
    name: str | None = None
    description: str | None = None
    workflow_status: str
    current_phase: str | None = None
    completed_phases: dict[str, bool] = Field(default_factory=dict)
    budget_state: dict[str, Any] = Field(default_factory=dict)
    context_items: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlanSessionListResponse(BaseModel):
    """Response for listing plan sessions."""

    sessions: list[PlanSessionResponse]
    total: int


class PlanSessionDetailResponse(PlanSessionResponse):
    """Full session detail including fingerprints."""

    fingerprints: dict[str, Any] = Field(default_factory=dict)


class PlanSessionUpdateRequest(BaseModel):
    """Request body for updating a plan session."""

    name: str = Field(..., min_length=1, max_length=255)


class PlanSessionUpdateResponse(BaseModel):
    """Response after updating a plan session."""

    id: str
    name: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlanSessionDeleteResponse(BaseModel):
    """Response after deleting a plan session."""

    success: bool
    session_id: str


class PlanDocumentResponse(BaseModel):
    """Response for a plan document."""

    id: str
    storage_key: str
    original_filename: str
    mime_type: str
    file_size: int
    file_hash: str | None = None
    document_type: str = "supporting"
    uploaded_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanDocumentUploadResponse(BaseModel):
    """Response after uploading a plan document."""

    id: str
    original_filename: str
    mime_type: str
    file_size: int
    document_type: str

    model_config = {"from_attributes": True}


class PlanDocumentListResponse(BaseModel):
    """Response listing documents for a plan session."""

    documents: list[PlanDocumentResponse]
    total: int
