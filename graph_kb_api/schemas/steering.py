"""
Pydantic schemas for steering document endpoints.
"""

from datetime import datetime
from typing import List

from pydantic import BaseModel


class SteeringDocResponse(BaseModel):
    """Single steering document response."""

    filename: str
    content: str
    created_at: datetime


class SteeringListResponse(BaseModel):
    """List of steering documents."""

    documents: List[SteeringDocResponse]
    total: int
