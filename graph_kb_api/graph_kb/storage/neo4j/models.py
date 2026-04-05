"""Data models for Neo4j RAG query results.

This module provides structured result types for unified RAG queries
that combine vector search with graph context expansion.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UnifiedRAGResult:
    """Result from unified RAG query combining vector search with graph context.

    This dataclass represents a single result from the unified RAG query,
    containing chunk content along with file context, symbol context, and
    related symbol information.

    Attributes:
        chunk_id: The unique identifier of the chunk node (UUID string).
        chunk_content: The actual code/text content of the chunk.
        start_line: Starting line number of the chunk in the source file.
        end_line: Ending line number of the chunk in the source file.
        similarity_score: Similarity score from the vector search (0.0 to 1.0).
        file_path: Path to the source file containing this chunk.
        symbol_name: Name of the symbol this chunk represents (if any).
        symbol_kind: Kind of symbol (function, class, method, etc.) if any.
        related_symbols: List of related symbols via CALLS/IMPORTS/USES relationships.
        is_documentation: True if this chunk is from a markdown documentation file.
    """

    chunk_id: str
    chunk_content: str
    start_line: int
    end_line: int
    similarity_score: float
    file_path: str
    symbol_name: Optional[str] = None
    symbol_kind: Optional[str] = None
    related_symbols: List[Dict[str, Any]] = field(default_factory=list)
    is_documentation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON encoding.

        Returns:
            Dictionary representation of the UnifiedRAGResult suitable
            for JSON serialization.
        """
        return {
            "chunk_id": self.chunk_id,
            "chunk_content": self.chunk_content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "similarity_score": self.similarity_score,
            "file_path": self.file_path,
            "symbol_name": self.symbol_name,
            "symbol_kind": self.symbol_kind,
            "related_symbols": self.related_symbols,
            "is_documentation": self.is_documentation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedRAGResult":
        """Deserialize from dictionary.

        Args:
            data: Dictionary containing UnifiedRAGResult fields.

        Returns:
            UnifiedRAGResult instance reconstructed from the dictionary.

        Raises:
            KeyError: If required fields are missing from the dictionary.
            TypeError: If field types don't match expected types.
        """
        return cls(
            chunk_id=data["chunk_id"],
            chunk_content=data["chunk_content"],
            start_line=data["start_line"],
            end_line=data["end_line"],
            similarity_score=data["similarity_score"],
            file_path=data["file_path"],
            symbol_name=data.get("symbol_name"),
            symbol_kind=data.get("symbol_kind"),
            related_symbols=data.get("related_symbols", []),
            is_documentation=data.get("is_documentation", False),
        )
