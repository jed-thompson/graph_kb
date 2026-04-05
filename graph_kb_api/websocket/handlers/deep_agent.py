"""
Deep agent workflow handler.

Handles iterative reasoning and deep code analysis workflows over WebSocket.
"""

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.websocket.handlers.ask_code import _fallback_ask_code
from graph_kb_api.websocket.handlers.base import (
    DEEP_AGENT_NODE_PHASES,
    logger,
)
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.progress import stream_workflow_with_progress
from graph_kb_api.websocket.protocol import AskCodePayload, DeepAgentPayload


async def handle_deep_agent_workflow(
    client_id: str,
    workflow_id: str,
    payload: DeepAgentPayload,
) -> None:
    """Handle the deep agent (LangGraph) workflow with iterative reasoning."""
    try:
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "step": "initializing",
                "phase": "initializing",
                "progress_percent": -1,
                "message": "Starting deep analysis...",
                "intent": "deep_analysis",
            },
        )

        from graph_kb_api.context import get_app_context

        app_context = get_app_context()

        try:
            from graph_kb_api.flows.v3.graphs.deep_agent import DeepAgentWorkflowEngine

            engine = DeepAgentWorkflowEngine(
                llm=app_context.llm,
                app_context=app_context,
                checkpointer=None,
            )

            result = await stream_workflow_with_progress(
                engine=engine,
                client_id=client_id,
                workflow_id=workflow_id,
                manager=manager,
                query=payload.query,
                repo_id=payload.repo_id,
                node_phase_map=DEEP_AGENT_NODE_PHASES,
                has_cycles=False,
            )

            await manager.send_event(
                client_id=client_id,
                event_type="complete",
                workflow_id=workflow_id,
                data={
                    "response": result.get(
                        "final_output", result.get("llm_response", "")
                    ),
                    "visualization": result.get("mermaid_code"),
                    "context_items": result.get("context_items", []),
                },
            )

        except (ImportError, TypeError) as e:
            logger.warning(f"DeepAgentWorkflowEngine not available: {e}")
            facade = get_graph_kb_facade()
            await _fallback_ask_code(
                client_id,
                workflow_id,
                AskCodePayload(query=payload.query, repo_id=payload.repo_id),
                facade,
            )

    except Exception as e:
        logger.error(f"Deep agent workflow error: {e}", exc_info=True)
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={"message": str(e), "code": "DEEP_AGENT_ERROR"},
        )
    finally:
        await manager.complete_workflow(workflow_id)
