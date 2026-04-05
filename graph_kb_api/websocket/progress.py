"""
Progress event types for WebSocket workflow feedback.

Provides a standardized ProgressEvent dataclass used by all workflows
to emit consistent progress data over WebSocket connections.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
    from graph_kb_api.websocket.manager import ConnectionManager


@dataclass
class ProgressEvent:
    """Standardized progress event for all workflows.

    Attributes:
        phase: Current phase identifier (e.g., "cloning", "indexing", "reasoning").
        message: Human-readable status message.
        progress_percent: 0-100 for determinate progress, or -1 for indeterminate.
        detail: Optional workflow-specific extra data merged into the output.
    """

    phase: str
    message: str
    progress_percent: float = -1
    detail: Optional[Dict[str, Any]] = field(default=None)

    def __post_init__(self) -> None:
        if not self.phase:
            raise ValueError("phase must be a non-empty string")
        if not self.message:
            raise ValueError("message must be a non-empty string")
        if self.progress_percent != -1 and not (0 <= self.progress_percent <= 100):
            raise ValueError(
                "progress_percent must be -1 (indeterminate) or in the range [0, 100]"
            )

    def to_send_data(self) -> Dict[str, Any]:
        """Convert to the dict sent via send_event data param.

        Returns a dict containing both ``phase`` and ``step`` keys
        (``step`` mirrors ``phase`` for backward compatibility).
        If ``detail`` is set, its entries are merged into the result.
        """
        result: Dict[str, Any] = {
            "phase": self.phase,
            "step": self.phase,  # backward compat
            "progress_percent": self.progress_percent,
            "message": self.message,
        }
        if self.detail:
            result.update(self.detail)
        return result


class ThreadSafeBridge:
    """Bridges sync callbacks from worker threads to async WebSocket sends.

    Accepts progress events from synchronous code running in threads and
    safely enqueues them onto the asyncio event loop via
    ``call_soon_threadsafe``.  The ``send`` method never blocks the calling
    thread and never raises, even if the event loop has already been closed.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,  # type: ignore[type-arg]
        workflow_id: str = "unknown",
    ) -> None:
        self.loop = loop
        self.queue = queue
        self.workflow_id = workflow_id
        self._events_sent = 0
        self._events_dropped = 0

    def send(self, event: dict) -> None:
        """Thread-safe: schedule *event* onto the async queue.

        Catches ``RuntimeError`` if the event loop is closed (e.g. the
        workflow is shutting down) and logs the dropped event.
        """
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, event)
            self._events_sent += 1
            # Log every 10 events to track progress without spam
            if self._events_sent % 10 == 0:
                logger.debug(
                    "ThreadSafeBridge progress | workflow_id=%s events_sent=%d queue_size=%d",
                    self.workflow_id,
                    self._events_sent,
                    self.queue.qsize(),
                )
        except RuntimeError as e:
            # Event loop is closed — workflow is shutting down
            self._events_dropped += 1
            logger.warning(
                "ThreadSafeBridge event dropped (event loop closed) | workflow_id=%s "
                "events_dropped=%d total_sent=%d error=%s",
                self.workflow_id,
                self._events_dropped,
                self._events_sent,
                str(e),
            )
        except Exception as e:
            # Unexpected error - log with full details
            self._events_dropped += 1
            logger.error(
                "ThreadSafeBridge unexpected error | workflow_id=%s error=%s event_phase=%s",
                self.workflow_id,
                str(e),
                event.get("phase", "unknown"),
                exc_info=True,
            )

    def get_stats(self) -> Dict[str, int]:
        """Return statistics about events sent and dropped."""
        return {
            "events_sent": self._events_sent,
            "events_dropped": self._events_dropped,
            "queue_size": self.queue.qsize(),
        }


async def consume_progress_queue(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    client_id: str,
    workflow_id: str,
    manager: ConnectionManager,
) -> None:
    """Consume progress events from the queue and send via WebSocket.

    Loops on ``await queue.get()``, forwarding each event to the client
    through ``manager.send_event()``.  Stops when a ``None`` sentinel is
    received, ensuring clean shutdown.

    Args:
        queue: The asyncio queue populated by :class:`ThreadSafeBridge`.
        client_id: Target WebSocket client identifier.
        workflow_id: Associated workflow identifier.
        manager: The :class:`ConnectionManager` used to send events.
    """
    events_consumed = 0
    send_failures = 0

    logger.info(
        "Progress consumer started | workflow_id=%s client_id=%s",
        workflow_id,
        client_id,
    )

    try:
        while True:
            try:
                event = await queue.get()
                if event is None:  # Sentinel to stop
                    logger.info(
                        "Progress consumer received sentinel, shutting down | "
                        "workflow_id=%s events_consumed=%d send_failures=%d",
                        workflow_id,
                        events_consumed,
                        send_failures,
                    )
                    break

                events_consumed += 1
                success = await manager.send_event(
                    client_id=client_id,
                    event_type="progress",
                    workflow_id=workflow_id,
                    data=event,
                )

                # Log every 20th event at INFO so progress is visible in container logs
                if events_consumed % 20 == 0 or events_consumed <= 2:
                    logger.info(
                        "Progress consumer forwarding | workflow_id=%s "
                        "events=%d phase=%s sent=%s",
                        workflow_id,
                        events_consumed,
                        event.get("phase", "?"),
                        success,
                    )

                if not success:
                    send_failures += 1
                    if send_failures == 1:
                        # Log first failure with details, subsequent at debug level
                        logger.warning(
                            "Progress send failed (client may have disconnected) | "
                            "workflow_id=%s client_id=%s event_phase=%s",
                            workflow_id,
                            client_id,
                            event.get("phase", "unknown"),
                        )
                    elif send_failures % 10 == 0:
                        logger.debug(
                            "Progress send failures accumulating | workflow_id=%s failures=%d",
                            workflow_id,
                            send_failures,
                        )

            except asyncio.CancelledError:
                logger.info(
                    "Progress consumer cancelled | workflow_id=%s events_consumed=%d",
                    workflow_id,
                    events_consumed,
                )
                raise
            except Exception as e:
                logger.error(
                    "Progress consumer error processing event | workflow_id=%s error=%s",
                    workflow_id,
                    str(e),
                    exc_info=True,
                )
                # Continue processing - don't let one bad event stop the queue
    finally:
        logger.info(
            "Progress consumer finished | workflow_id=%s events_consumed=%d send_failures=%d",
            workflow_id,
            events_consumed,
            send_failures,
        )


async def stream_workflow_with_progress(
    engine: BaseWorkflowEngine,
    client_id: str,
    workflow_id: str,
    manager: ConnectionManager,
    query: str,
    repo_id: str,
    node_phase_map: Dict[str, str],
    has_cycles: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Stream a LangGraph workflow, emitting progress events for each node.

    Iterates ``engine.start_workflow_stream()`` (an async generator yielding
    ``{node_name: state_update}`` dicts) and sends a progress event for every
    non-``__end__`` node transition.

    For linear workflows (``has_cycles=False``), ``progress_percent`` is
    computed as ``(nodes_completed / total_nodes) * 100`` capped at 100.
    For cyclic workflows (``has_cycles=True``), ``progress_percent`` and
    ``total_nodes`` are both set to ``-1`` (indeterminate).

    Args:
        engine: A properly instantiated workflow engine.
        client_id: Target WebSocket client identifier.
        workflow_id: Associated workflow identifier.
        manager: The :class:`ConnectionManager` used to send events.
        query: The user query to pass to the engine.
        repo_id: Repository identifier for the workflow.
        node_phase_map: Mapping of LangGraph node names to human-readable phases.
        has_cycles: Whether the workflow graph contains cycles.
        **kwargs: Extra keyword arguments forwarded to ``start_workflow_stream``.

    Returns:
        The accumulated final state dict from all node updates.
    """
    nodes_completed = 0
    total_nodes = -1 if has_cycles else len(node_phase_map)
    final_state: Dict[str, Any] = {}

    async for chunk in engine.start_workflow_stream(
        user_query=query,
        user_id=client_id,
        session_id=workflow_id,
        repo_id=repo_id,
        **kwargs,
    ):
        for node_name, state_update in chunk.items():
            if node_name == "__end__":
                continue

            nodes_completed += 1
            phase = node_phase_map.get(node_name, node_name)

            if has_cycles:
                progress_pct: float = -1
            else:
                progress_pct = min((nodes_completed / total_nodes) * 100, 100)

            await manager.send_event(
                client_id=client_id,
                event_type="progress",
                workflow_id=workflow_id,
                data={
                    "phase": phase,
                    "step": phase,
                    "progress_percent": progress_pct,
                    "message": f"{phase}...",
                    "node": node_name,
                    "nodes_completed": nodes_completed,
                    "total_nodes": total_nodes,
                },
            )
            final_state.update(state_update)

    return final_state
