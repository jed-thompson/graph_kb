"""
Symbol Pydantic schemas.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SymbolKind(str, Enum):
    """Type of code symbol."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    MODULE = "module"
    VARIABLE = "variable"


class SymbolResponse(BaseModel):
    """Symbol details response."""
    id: str
    name: str
    kind: SymbolKind
    file_path: str
    start_line: int
    end_line: int
    docstring: Optional[str] = None
    signature: Optional[str] = None

    class Config:
        from_attributes = True


class SymbolSearchRequest(BaseModel):
    """Symbol search parameters."""
    pattern: Optional[str] = None
    kind: Optional[SymbolKind] = None
    file_pattern: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=500)


class SymbolNeighborsRequest(BaseModel):
    """Request for symbol neighbors."""
    direction: str = Field(default="both", pattern="^(incoming|outgoing|both)$")
    edge_types: Optional[List[str]] = None
    limit: int = Field(default=50, ge=1, le=200)


class PathRequest(BaseModel):
    """Request for path between symbols."""
    from_symbol: str
    to_symbol: str
    max_hops: int = Field(default=5, ge=1, le=10)


class PathResponse(BaseModel):
    """Path between symbols response."""
    path: List[SymbolResponse]
    path_length: int
