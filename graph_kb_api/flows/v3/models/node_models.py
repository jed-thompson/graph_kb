"""
Node execution models for workflow nodes.

This module contains dataclasses and enums related to workflow node
execution, results, and status tracking.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional


class NodeExecutionStatus(str, Enum):
    """Status of node execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class NodeExecutionResult:
    """Result of node execution with metadata."""

    status: NodeExecutionStatus
    output: Dict[str, Any]
    error: Optional[Exception] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0
    execution_time_ms: int = 0
    next_node: Optional[str] = None

    @classmethod
    def success(
        cls,
        output: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None,
        tokens_used: int = 0,
        next_node: Optional[str] = None,
    ) -> "NodeExecutionResult":
        """Create a successful execution result."""
        return cls(
            status=NodeExecutionStatus.SUCCESS,
            output=output or {},
            metadata=metadata or {},
            tokens_used=tokens_used,
            next_node=next_node,
        )

    @classmethod
    def failure(
        cls,
        error_message: str,
        metadata: Dict[str, Any] | None = None,
        tokens_used: int = 0,
        error_exception: Optional[Exception] = None,
    ) -> "NodeExecutionResult":
        """Create a failed execution result."""
        error_obj: Exception = error_exception if error_exception is not None else Exception(error_message)
        return cls(
            status=NodeExecutionStatus.FAILURE,
            output={},
            error=error_obj,
            metadata=metadata or {},
            tokens_used=tokens_used,
        )

    @classmethod
    def partial(
        cls,
        output: Dict[str, Any] | None = None,
        metadata: Dict[str, Any] | None = None,
        tokens_used: int = 0,
        next_node: Optional[str] = None,
    ) -> "NodeExecutionResult":
        """Create a partial execution result."""
        return cls(
            status=NodeExecutionStatus.PARTIAL,
            output=output or {},
            metadata=metadata or {},
            tokens_used=tokens_used,
            next_node=next_node,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for state storage."""
        return {
            "status": self.status.value,
            "output": self.output,
            "error": str(self.error) if self.error else None,
            "error_type": type(self.error).__name__ if self.error else None,
            "metadata": self.metadata or {},
            "tokens_used": self.tokens_used,
            "execution_time_ms": self.execution_time_ms,
            "next_node": self.next_node,
            "timestamp": datetime.now(UTC).isoformat(),
        }
