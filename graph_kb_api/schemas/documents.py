"""
Pydantic schemas for document management endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    """Single document response."""

    id: str
    filename: str
    parent: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    # New fields for S3 storage
    storage_key: Optional[str] = Field(None, description="S3/blob storage key")
    indexed_for_search: Optional[bool] = Field(None, description="Whether indexed in ChromaDB")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    mime_type: Optional[str] = Field(None, description="MIME type")


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    documents: List[DocumentResponse]
    total: int
    offset: int
    limit: int


class DocumentUploadRequest(BaseModel):
    """Request body for document upload."""

    filename: str
    parent: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentUpdateRequest(BaseModel):
    """Request body for document update/patch operations."""

    category: Optional[str] = Field(None, description="New category assignment")


class DocumentFilterOptions(BaseModel):
    """Available filter options for documents."""

    parents: List[str] = Field(default_factory=list, description="Distinct parent values")
    categories: List[str] = Field(default_factory=list, description="Distinct category values")
