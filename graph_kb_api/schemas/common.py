"""
Common Pydantic schemas for API responses.

Includes pagination, error responses, and base models.
"""

from datetime import datetime
from typing import Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

# Generic type for paginated responses
T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str
    error_type: str = "error"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginationParams(BaseModel):
    """Pagination parameters."""
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: List[T]
    total: int
    offset: int
    limit: int
    has_more: bool


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    services: Optional[Dict[str, bool]] = None
