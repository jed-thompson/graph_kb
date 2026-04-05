"""
Pydantic schemas for chat and LLM endpoints.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class AskCodeRequest(BaseModel):
    """Request body for code Q&A."""

    repo_id: Optional[str] = None
    query: str = Field(min_length=1, max_length=10000)
    top_k: int = Field(default=10, ge=1, le=100)
    max_depth: int = Field(default=3, ge=1, le=10)
    use_deep_agent: bool = False


class SourceItem(BaseModel):
    """A source reference from code retrieval."""

    file_path: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    content: Optional[str] = None
    symbol: Optional[str] = None
    score: Optional[float] = None


class AskCodeResponse(BaseModel):
    """Response from code Q&A."""

    answer: str
    sources: List[SourceItem]
    mermaid_diagrams: List[str] = Field(default_factory=list)
    tokens_used: Optional[int] = None
    model: Optional[str] = None
    intent: Optional[str] = None  # Detected intent (e.g., 'ask_code', 'deep_analysis')
    workflow_id: Optional[str] = None  # For sources page navigation
