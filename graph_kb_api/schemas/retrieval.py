"""
Retrieval and search Pydantic schemas.
"""

from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    """Semantic search request."""

    query: str
    top_k: int = Field(default=30, ge=1, le=100)
    max_depth: int = Field(default=5, ge=1, le=10)
    include_graph_expansion: bool = True


class ContextItemResponse(BaseModel):
    """Single context item from retrieval."""

    id: str
    file_path: str
    start_line: int
    end_line: int
    content: str
    symbol: Optional[str] = None
    score: float
    source: str = "vector"  # "vector", "graph", "anchor"


class SearchResponse(BaseModel):
    """Search results response."""

    items: List[ContextItemResponse]
    total_found: int
    vector_search_duration: float
    graph_expansion_duration: Optional[float] = None


class RetrieveRequest(BaseModel):
    """Full hybrid retrieval request."""

    query: str
    top_k: int = Field(default=30, ge=1, le=100)
    max_depth: int = Field(default=5, ge=1, le=10)
    current_file: Optional[str] = None
    error_stack: Optional[Union[str, List[str]]] = None

    @field_validator("error_stack", mode="before")
    @classmethod
    def coerce_error_stack(cls, v):
        """Accept both a single string and a list of strings."""
        if isinstance(v, list):
            return "\n".join(v)
        return v


class RetrieveResponse(BaseModel):
    """Full retrieval response with context."""

    items: List[ContextItemResponse]
    total_found: int
    vector_search_duration: float
    graph_expansion_duration: Optional[float] = None
    visualization: Optional[str] = None  # Mermaid diagram
