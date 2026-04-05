"""
WebSocket connection manager.

Manages active WebSocket connections and running workflows.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from graph_kb_api.utils.timeout_config import TimeoutConfig

logger = logging.getLogger(__name__)


@dataclass
class WorkflowState:
    """State for a running workflow."""

    workflow_id: str
    workflow_type: str  # "ask-code", "ingest", "diff"
    client_id: str
    status: str = "running"  # "running", "paused", "complete", "error"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_event_id: int = 0
    task: Optional[asyncio.Task] = None

    async def cancel(self):
        """Cancel the running workflow."""
        if self.task and not self.task.done():
            self.task.cancel()
            self.status = "cancelled"


class ConnectionManager:
    """
    Manages WebSocket connections and workflow state.

    Responsibilities:
    - Track active WebSocket connections by client_id
    - Track running workflows per connection
    - Handle graceful disconnect and cleanup
    - Provide progress callback factory for workflows
    """

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.workflows: Dict[str, WorkflowState] = {}
        self._session_to_client: Dict[str, str] = {}
        self.keepalive_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        """
        Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection
            client_id: Unique identifier for this client
        """
        await websocket.accept()
        async with self._lock:
            self.active_connections[client_id] = websocket
        logger.info(f"Client {client_id} connected. Total connections: {len(self.active_connections)}")

        keepalive_interval = TimeoutConfig.get_websocket_keepalive_interval()

        async def _keepalive_loop() -> None:
            while True:
                await asyncio.sleep(keepalive_interval)
                try:
                    await self.send_event(
                        client_id=client_id,
                        event_type="ping",
                        workflow_id="system",
                        data={"timestamp": datetime.now(UTC).isoformat()},
                    )
                except Exception:
                    break  # Client disconnected, disconnect() will clean up

        async with self._lock:
            self.keepalive_tasks[client_id] = asyncio.create_task(_keepalive_loop())

    async def disconnect(self, client_id: str) -> None:
        """
        Handle client disconnection.

        Removes the WebSocket connection but *preserves* running workflow
        state so the client can reconnect and resume progress.  Only
        workflows that are already complete or errored are cleaned up.

        Args:
            client_id: The disconnecting client's ID
        """
        async with self._lock:
            # Clean up keepalive task
            if client_id in self.keepalive_tasks:
                task = self.keepalive_tasks.pop(client_id)
                if not task.done():
                    task.cancel()

            # Remove connection
            if client_id in self.active_connections:
                del self.active_connections[client_id]

            # Preserve running/paused workflows for reconnection.
            # Only remove workflows that are already terminal.
            terminal = [
                wf_id
                for wf_id, wf in self.workflows.items()
                if wf.client_id == client_id and wf.status in ("complete", "cancelled", "error")
            ]
            for wf_id in terminal:
                del self.workflows[wf_id]

            # Clean up stale session → client mappings for this client.
            stale = [sid for sid, cid in self._session_to_client.items() if cid == client_id]
            for sid in stale:
                del self._session_to_client[sid]

        logger.info(f"Client {client_id} disconnected. Total connections: {len(self.active_connections)}")

    async def send_event(
        self,
        client_id: str,
        event_type: str,
        workflow_id: str,
        data: Dict[str, Any],
    ) -> bool:
        """
        Send an event to a specific client.

        Args:
            client_id: Target client ID
            event_type: Type of event (progress, tool_call, complete, error, etc.)
            workflow_id: Associated workflow ID
            data: Event payload

        Returns:
            True if event was sent successfully, False otherwise
        """
        if client_id not in self.active_connections:
            return False

        try:
            # Get next event ID for this workflow
            event_id = self._get_next_event_id(workflow_id)

            event = {
                "type": event_type,
                "workflow_id": workflow_id,
                "event_id": str(event_id),
                "data": data,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            await self.active_connections[client_id].send_json(event)
            return True

        except WebSocketDisconnect:
            await self.disconnect(client_id)
            return False
        except Exception as e:
            logger.error(f"Failed to send event to {client_id}: {e}")
            return False

    def _get_next_event_id(self, workflow_id: str) -> int:
        """Get and increment the event ID for a workflow."""
        if workflow_id in self.workflows:
            self.workflows[workflow_id].last_event_id += 1
            return self.workflows[workflow_id].last_event_id
        return 1

    def create_workflow(
        self,
        client_id: str,
        workflow_type: str,
        task: Optional[asyncio.Task] = None,
    ) -> str:
        """
        Create a new workflow for a client.

        Args:
            client_id: Client owning this workflow
            workflow_type: Type of workflow (ask-code, ingest, etc.)
            task: Optional asyncio task running the workflow

        Returns:
            The generated workflow_id
        """
        workflow_id = str(uuid.uuid4())
        self.workflows[workflow_id] = WorkflowState(
            workflow_id=workflow_id,
            workflow_type=workflow_type,
            client_id=client_id,
            task=task,
        )
        return workflow_id

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get a workflow by ID."""
        return self.workflows.get(workflow_id)

    async def complete_workflow(
        self,
        workflow_id: str,
        status: str = "complete",
    ) -> None:
        """Mark a workflow as complete."""
        if workflow_id in self.workflows:
            self.workflows[workflow_id].status = status

    def register_session(self, session_id: str, client_id: str) -> None:
        """Associate a *session_id* (e.g. plan session) with a *client_id*."""
        self._session_to_client[session_id] = client_id

    def unregister_session(self, session_id: str) -> None:
        """Remove a session → client mapping."""
        self._session_to_client.pop(session_id, None)

    async def broadcast_to_session(
        self,
        session_id: str,
        event_type: str,
        data: Dict[str, Any],
    ) -> bool:
        """Send an event to the client that owns *session_id*."""
        client_id = self._session_to_client.get(session_id)
        if not client_id:
            logger.warning(
                "broadcast_to_session: no client_id for session %s, dropping %s",
                session_id,
                event_type,
            )
            return False
        return await self.send_event(
            client_id=client_id,
            event_type=event_type,
            workflow_id=session_id,
            data=data,
        )

    def create_progress_callback(
        self,
        client_id: str,
        workflow_id: str,
    ) -> Callable:
        """
        Create a progress callback for workflow progress updates.

        The returned callback can be passed to workflow engines to stream
        progress updates to the client.

        Args:
            client_id: Target client ID
            workflow_id: Associated workflow ID

        Returns:
            Async callback function(step: str, current: int, total: int)
        """

        async def callback(step: str, current: int = 0, total: int = 0, **kwargs):
            await self.send_event(
                client_id=client_id,
                event_type="progress",
                workflow_id=workflow_id,
                data={
                    "step": step,
                    "current": current,
                    "total": total,
                    **kwargs,
                },
            )

        return callback

    def create_tool_call_callback(
        self,
        client_id: str,
        workflow_id: str,
    ) -> Callable:
        """
        Create a callback for tool call notifications.

        Args:
            client_id: Target client ID
            workflow_id: Associated workflow ID

        Returns:
            Async callback function(tool_name: str, args: dict, result: any)
        """

        async def callback(tool_name: str, args: Dict[str, Any], result: Any = None):
            await self.send_event(
                client_id=client_id,
                event_type="tool_call",
                workflow_id=workflow_id,
                data={
                    "tool": tool_name,
                    "args": args,
                    "result": result,
                },
            )

        return callback


# Global connection manager instance
manager = ConnectionManager()
