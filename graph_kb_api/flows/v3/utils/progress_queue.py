"""
Progress queue for granular SSE updates during workflow execution.

This module provides an async queue that allows workflow nodes to emit
progress events that can be picked up by the SSE streaming layer.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional


@dataclass
class ProgressEvent:
    """A single progress event."""
    step: str
    phase: str
    progress_percent: float
    message: str
    details: Optional[Dict[str, Any]] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'type': 'progress',
            'step': self.step,
            'phase': self.phase,
            'progress_percent': round(self.progress_percent, 1),
            'message': self.message,
            'details': self.details or {},
            'timestamp': self.timestamp,
        }


class ProgressQueue:
    """
    Async queue for progress events during workflow execution.

    This allows nodes to emit progress events that can be consumed
    by the SSE streaming layer without blocking the workflow.
    """

    def __init__(self, max_size: int = 100):
        """Initialize the progress queue."""
        self._queue: asyncio.Queue[Optional[ProgressEvent]] = asyncio.Queue(maxsize=max_size)
        self._closed = False

    async def emit(self, event: ProgressEvent) -> None:
        """
        Emit a progress event to the queue.

        Args:
            event: Progress event to emit
        """
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop event if queue is full (prevents blocking)
            pass

    def emit_nowait(self, event: ProgressEvent) -> None:
        """
        Emit a progress event without waiting (for sync contexts).

        Args:
            event: Progress event to emit
        """
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    async def get(self) -> Optional[ProgressEvent]:
        """
        Get the next progress event from the queue.

        Returns:
            Progress event or None if queue is closed and empty
        """
        return await self._queue.get()

    def close(self) -> None:
        """Close the queue (signals end of events)."""
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

    @property
    def is_closed(self) -> bool:
        """Check if the queue is closed."""
        return self._closed

    async def __aiter__(self) -> AsyncIterator[ProgressEvent]:
        """Iterate over progress events until queue is closed."""
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event


# Step definitions for retrieval progress (matches progress_display.py)
RETRIEVAL_STEPS = {
    'initializing': (1, 8, "Initializing"),
    'question_analyzed': (2, 8, "Question analyzed"),
    'embedding_generation': (3, 8, "Generating embeddings"),
    'vector_search': (4, 8, "Vector similarity search"),
    'graph_expansion': (5, 8, "Graph expansion"),
    'context_ranking': (6, 8, "Ranking & pruning context"),
    'agent_analyzing': (7, 8, "Agent analyzing context"),
    'formatting_response': (8, 8, "Formatting response"),
    'complete': (8, 8, "Complete"),
}


def create_retrieval_progress_event(
    step: str,
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> ProgressEvent:
    """
    Create a progress event for retrieval steps.

    Args:
        step: Step identifier (e.g., 'vector_search', 'graph_expansion')
        message: Human-readable message
        details: Optional additional details

    Returns:
        ProgressEvent with calculated progress percentage
    """
    step_num, total_steps, phase = RETRIEVAL_STEPS.get(step, (0, 8, step))
    progress_percent = (step_num / total_steps) * 100

    return ProgressEvent(
        step=step,
        phase=phase,
        progress_percent=progress_percent,
        message=message,
        details=details or {},
    )
