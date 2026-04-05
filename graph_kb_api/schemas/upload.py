"""
Pydantic schemas for file upload classification.
"""

from typing import Literal

from pydantic import BaseModel


class FileUploadClassification(BaseModel):
    """Classification metadata for an uploaded file."""

    parent_name: str
    category: Literal["supporting_docs", "technical_specs"]
    collection_name: str


class FileUploadResult(BaseModel):
    """Summary result of a file upload batch."""

    success: int
    skipped: int
    errors: int
    total_chunks: int
