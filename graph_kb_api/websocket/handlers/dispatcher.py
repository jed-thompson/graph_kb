"""
WebSocket message dispatcher.

Routes incoming WebSocket messages to appropriate workflow handlers.
Supports start, input, cancel, reconnect, and action message types.
"""

import asyncio
from typing import Any, Dict, Optional

from fastapi import WebSocket

from graph_kb_api.schemas.websocket import (
    WSInputPayload,
    WSStartPayload,
)
from graph_kb_api.websocket.handlers.ask_code import handle_ask_code_workflow
from graph_kb_api.websocket.handlers.base import (
    _debug_log,
    logger,
)
from graph_kb_api.websocket.handlers.deep_agent import handle_deep_agent_workflow
from graph_kb_api.websocket.handlers.ingest import handle_ingest_workflow
from graph_kb_api.websocket.handlers.multi_agent import handle_multi_agent_workflow
from graph_kb_api.websocket.handlers.plan_dispatcher import dispatch_plan_message
from graph_kb_api.websocket.handlers.research_dispatcher import dispatch_research_message
from graph_kb_api.websocket.manager import manager
from graph_kb_api.schemas.websocket import VALID_WORKFLOW_TYPES
from graph_kb_api.websocket.protocol import (
    ActionPayload,
    AskCodePayload,
    ClientMessage,
    DeepAgentPayload,
    IngestPayload,
    MultiAgentPayload,
    ReconnectPayload,
)


async def _handle_start(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle a 'start' message: validate workflow_type and route."""
    _debug_log(
        "HANDLE_START_ENTRY",
        client_id=client_id,
        payload_keys=list(payload.keys()),
        workflow_type=payload.get("workflow_type", "MISSING"),
        has_git_url="git_url" in payload,
    )
    try:
        start_payload = WSStartPayload(**payload)
    except Exception as e:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id="",
            data={
                "message": f"Invalid start payload: {e}",
                "code": "INVALID_PAYLOAD",
            },
        )
        return

    workflow_type = start_payload.workflow_type
    if workflow_type not in VALID_WORKFLOW_TYPES:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id="",
            data={
                "message": f"Unknown workflow type: {workflow_type}. "
                f"Must be one of: {', '.join(sorted(VALID_WORKFLOW_TYPES))}",
                "code": "INVALID_WORKFLOW_TYPE",
            },
        )
        return

    workflow_id = manager.create_workflow(client_id, workflow_type)

    # Acknowledge start
    await manager.send_event(
        client_id=client_id,
        event_type="progress",
        workflow_id=workflow_id,
        data={"step": "started", "workflow_id": workflow_id},
    )

    # Route to the correct handler
    if workflow_type == "ask-code":
        ask_payload = AskCodePayload(
            query=start_payload.query or "",
            repo_id=start_payload.repo_id or "",
        )
        asyncio.create_task(handle_ask_code_workflow(client_id, workflow_id, ask_payload))
    elif workflow_type == "ingest":
        try:
            ingest_payload = IngestPayload(**payload)
        except Exception as e:
            logger.error(
                "Failed to parse IngestPayload | workflow_id=%s error=%s payload_keys=%s",
                workflow_id,
                str(e),
                list(payload.keys()),
            )
            await manager.send_event(
                client_id=client_id,
                event_type="error",
                workflow_id=workflow_id,
                data={
                    "message": f"Invalid ingest payload: {e}. Required: git_url",
                    "code": "INVALID_INGEST_PAYLOAD",
                },
            )
            return
        logger.info(
            "Dispatching ingest workflow | workflow_id=%s client_id=%s git_url=%s",
            workflow_id,
            client_id,
            ingest_payload.git_url,
        )
        _debug_log(
            "DISPATCH_INGEST",
            workflow_id=workflow_id,
            client_id=client_id,
            git_url=ingest_payload.git_url,
            branch=ingest_payload.branch,
            payload_keys=list(payload.keys()),
        )
        asyncio.create_task(
            handle_ingest_workflow(client_id, workflow_id, ingest_payload),
            name=f"ingest-{workflow_id}",
        )
    elif workflow_type == "multi_agent":
        ma_payload = MultiAgentPayload(
            query=start_payload.task or start_payload.query or "",
            repo_id=start_payload.repo_id,
        )
        asyncio.create_task(handle_multi_agent_workflow(client_id, workflow_id, ma_payload))
    elif workflow_type == "deep":
        deep_payload = DeepAgentPayload(
            query=start_payload.query or "",
            repo_id=start_payload.repo_id or "",
        )
        asyncio.create_task(handle_deep_agent_workflow(client_id, workflow_id, deep_payload))


async def _handle_input(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle an 'input' message: validate thread_id/decision and resume workflow."""
    try:
        input_payload = WSInputPayload(**payload)
    except Exception as e:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id="",
            data={
                "message": f"Invalid input payload: {e}",
                "code": "INVALID_PAYLOAD",
            },
        )
        return

    thread_id = input_payload.thread_id

    # Find the workflow by thread_id
    workflow = manager.get_workflow(thread_id)
    if not workflow:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=thread_id,
            data={
                "message": f"No active workflow found for thread_id: {thread_id}",
                "code": "WORKFLOW_NOT_FOUND",
            },
        )
        return

    # Standard workflow resume (ask-code, ingest, etc.)
    decision = input_payload.decision
    if not decision:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=thread_id,
            data={
                "message": "Missing decision in input payload",
                "code": "INVALID_INPUT",
            },
        )
        return

    # Resume the LangGraph workflow with the user's decision
    try:
        from langgraph.types import Command

        command = Command(update={"user_approved_preview": decision})
        logger.info(f"Resuming workflow {thread_id} with decision: {decision}")
        # Store the command for the workflow to pick up
        workflow.pending_input = command  # type: ignore[attr-defined]
    except ImportError:
        logger.warning("LangGraph not available, storing decision as dict")
        workflow.pending_input = {"user_approved_preview": decision}  # type: ignore[attr-defined]

    await manager.send_event(
        client_id=client_id,
        event_type="progress",
        workflow_id=thread_id,
        data={
            "step": "input_received",
            "message": f"Decision '{decision}' received",
            "decision": decision,
        },
    )


async def _handle_cancel(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle a 'cancel' message: cancel the running workflow."""
    workflow_id = payload.get("workflow_id", "")
    if not workflow_id:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id="",
            data={
                "message": "Missing workflow_id in cancel message",
                "code": "MISSING_WORKFLOW_ID",
            },
        )
        return

    workflow = manager.get_workflow(workflow_id)
    if workflow:
        await workflow.cancel()
        await manager.send_event(
            client_id=client_id,
            event_type="complete",
            workflow_id=workflow_id,
            data={"status": "cancelled", "message": "Workflow cancelled"},
        )
        await manager.complete_workflow(workflow_id, status="cancelled")
    else:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={
                "message": f"No active workflow found for workflow_id: {workflow_id}",
                "code": "WORKFLOW_NOT_FOUND",
            },
        )


async def _handle_reconnect(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle a 'reconnect' message: resume progress events for an active workflow.

    When a client reconnects after a dropped connection, the workflow
    state has been preserved server-side.  Re-associate the client and
    send the current status so the UI can pick up where it left off.
    """
    try:
        reconnect_payload = ReconnectPayload(**payload)
    except Exception as e:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id="",
            data={
                "message": f"Invalid reconnect payload: {e}",
                "code": "INVALID_PAYLOAD",
            },
        )
        return

    workflow_id = reconnect_payload.workflow_id
    workflow = manager.get_workflow(workflow_id)

    if workflow and workflow.status in ("running", "paused"):
        # Re-associate the client with this workflow so future events
        # are delivered to the new WebSocket connection.
        workflow.client_id = client_id
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "step": "reconnected",
                "message": "Reconnected to active workflow",
                "workflow_type": workflow.workflow_type,
                "status": workflow.status,
            },
        )
    elif workflow and workflow.status in ("complete", "cancelled"):
        await manager.send_event(
            client_id=client_id,
            event_type="complete",
            workflow_id=workflow_id,
            data={
                "status": workflow.status,
                "message": f"Workflow already {workflow.status}",
            },
        )
    else:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={
                "message": f"No active workflow found for workflow_id: {workflow_id}",
                "code": "WORKFLOW_NOT_FOUND",
            },
        )


async def _handle_action(client_id: str, payload: Dict[str, Any]) -> None:
    """Handle an 'action' message: pause or resume ingestion workflows."""
    try:
        action_payload = ActionPayload(**payload)
    except Exception as e:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id="",
            data={
                "message": f"Invalid action payload: {e}",
                "code": "INVALID_PAYLOAD",
            },
        )
        return

    workflow_id = action_payload.workflow_id
    action = action_payload.action

    workflow = manager.get_workflow(workflow_id)
    if not workflow:
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={
                "message": f"No active workflow found for workflow_id: {workflow_id}",
                "code": "WORKFLOW_NOT_FOUND",
            },
        )
        return

    if workflow.workflow_type != "ingest":
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={
                "message": "Action messages are only supported for ingestion workflows",
                "code": "INVALID_ACTION_TARGET",
            },
        )
        return

    if action == "pause":
        workflow.status = "paused"
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "step": "paused",
                "message": "Ingestion paused",
                "phase": "paused",
            },
        )
    elif action == "resume":
        workflow.status = "running"
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "step": "resumed",
                "message": "Ingestion resumed",
                "phase": "indexing",
            },
        )


async def _handle_plan_message(
    client_id: str,
    msg_type: str,
    payload: Dict[str, Any],
    workflow_id: Optional[str],
) -> None:
    """Handle Plan command messages.

    Routes plan.* messages to the PlanDispatcher.

    Supported message types:
    - plan.start - Start new plan session
    - plan.phase.input - Submit phase input
    - plan.navigate - Navigate to phase
    - plan.resume - Resume session
    - plan.pause - Pause session
    - plan.retry - Retry failed phase
    """
    try:
        await dispatch_plan_message(client_id, msg_type, payload, workflow_id)

    except Exception as e:
        logger.error(f"Plan message handling error: {e}", exc_info=True)
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id or "",
            data={
                "message": f"Failed to handle plan message: {e}",
                "code": "PLAN_MESSAGE_ERROR",
            },
        )


async def _handle_research_message(
    client_id: str,
    msg_type: str,
    payload: Dict[str, Any],
    workflow_id: Optional[str],
) -> None:
    """Handle Research messages.

    Routes research.* messages to the ResearchDispatcher.

    Supported message types:
    - research.start - Start new research session
    - research.review.start - Start review of research
    - research.gap.answer - Answer a detected gap
    """
    try:
        await dispatch_research_message(client_id, msg_type, payload, workflow_id)

    except Exception as e:
        logger.error(f"Research message handling error: {e}", exc_info=True)
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id or "",
            data={
                "message": f"Failed to handle research message: {e}",
                "code": "RESEARCH_MESSAGE_ERROR",
            },
        )


async def process_message(
    client_id: str,
    websocket: WebSocket,
    message: Dict[str, Any],
) -> None:
    """
    Process an incoming WebSocket message.

    Routes to appropriate handler based on message type.
    Supports: start, input, cancel, reconnect, action.
    """
    try:
        msg = ClientMessage(**message)
        _debug_log(
            "WS_MESSAGE_RECEIVED",
            msg_type=msg.type,
            payload_keys=list(msg.payload.keys()) if msg.payload else [],
            workflow_id=msg.workflow_id,
        )

        if msg.type == "start":
            await _handle_start(client_id, msg.payload)

        elif msg.type == "input":
            await _handle_input(client_id, msg.payload)

        elif msg.type == "cancel":
            # Cancel payload can come in payload dict or as top-level workflow_id
            cancel_data = msg.payload
            if msg.workflow_id and "workflow_id" not in cancel_data:
                cancel_data["workflow_id"] = msg.workflow_id
            await _handle_cancel(client_id, cancel_data)

        elif msg.type == "reconnect":
            reconnect_data = msg.payload
            if msg.workflow_id and "workflow_id" not in reconnect_data:
                reconnect_data["workflow_id"] = msg.workflow_id
            await _handle_reconnect(client_id, reconnect_data)

        elif msg.type == "action":
            action_data = msg.payload
            if msg.workflow_id and "workflow_id" not in action_data:
                action_data["workflow_id"] = msg.workflow_id
            await _handle_action(client_id, action_data)

        elif msg.type.startswith("plan."):
            # Handle Plan command messages
            await _handle_plan_message(client_id, msg.type, msg.payload, msg.workflow_id)

        elif msg.type.startswith("research."):
            # Handle Research messages
            await _handle_research_message(client_id, msg.type, msg.payload, msg.workflow_id)

        else:
            await manager.send_event(
                client_id=client_id,
                event_type="error",
                workflow_id="",
                data={
                    "message": f"Unknown message type: {msg.type}",
                    "code": "UNKNOWN_MESSAGE_TYPE",
                },
            )

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        await websocket.send_json(
            {
                "type": "error",
                "data": {"message": str(e)},
            }
        )


# Alias for backward compatibility
async def dispatch_message(
    client_id: str,
    websocket: WebSocket,
    message: Dict[str, Any],
) -> None:
    """Alias for process_message for backward compatibility."""
    await process_message(client_id, websocket, message)
