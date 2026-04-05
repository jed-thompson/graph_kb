"""
Multi-agent workflow handler.

Handles parallel agent execution workflows over WebSocket.
"""

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.websocket.handlers.base import (
    MULTI_AGENT_NODE_PHASES,
    logger,
)
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.progress import stream_workflow_with_progress
from graph_kb_api.websocket.protocol import MultiAgentPayload


async def handle_multi_agent_workflow(
    client_id: str,
    workflow_id: str,
    payload: MultiAgentPayload,
) -> None:
    """Handle multi-agent workflow with parallel agent execution.

    If one agent fails, the workflow continues executing other agents
    and includes partial results in the final response.
    """
    try:
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "step": "initializing",
                "phase": "initializing",
                "progress_percent": -1,
                "message": "Starting multi-agent workflow...",
            },
        )

        from graph_kb_api.context import get_app_context

        app_context = get_app_context()

        try:
            from graph_kb_api.flows.v3.graphs.multi_agent import (
                MultiAgentWorkflowEngine,
            )

            engine = MultiAgentWorkflowEngine(
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
                node_phase_map=MULTI_AGENT_NODE_PHASES,
                has_cycles=True,
            )

            await manager.send_event(
                client_id=client_id,
                event_type="complete",
                workflow_id=workflow_id,
                data={
                    "response": result.get("formatted_output", ""),
                    "agent_results": result.get("agent_outputs", {}),
                    "review_summary": result.get("review_summary", {}),
                },
            )

        except (ImportError, TypeError) as e:
            logger.warning(f"MultiAgentWorkflowEngine not available: {e}")
            facade = get_graph_kb_facade()
            await _fallback_multi_agent(client_id, workflow_id, payload, facade)

    except Exception as e:
        logger.error(f"Multi-agent workflow error: {e}", exc_info=True)
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={"message": str(e), "code": "MULTI_AGENT_ERROR"},
        )
    finally:
        await manager.complete_workflow(workflow_id)


async def _fallback_multi_agent(
    client_id: str,
    workflow_id: str,
    payload: MultiAgentPayload,
    facade,
) -> None:
    """Fallback multi-agent using retrieval service directly."""
    progress = manager.create_progress_callback(client_id, workflow_id)
    await progress("retrieving", message="Analyzing code...")

    retrieval_service = facade.retrieval_service
    result = retrieval_service.retrieve(
        repo_id=payload.repo_id,
        query=payload.query,
        top_k=30,
    )

    await progress("complete", message="Analysis complete")

    context_items = []
    if hasattr(result, "context_items"):
        for item in result.context_items[:10]:
            context_items.append(
                {
                    "file_path": item.file_path,
                    "content": item.content[:500],
                    "score": getattr(item, "score", 0),
                }
            )

    await manager.send_event(
        client_id=client_id,
        event_type="complete",
        workflow_id=workflow_id,
        data={
            "response": f"Retrieved {len(context_items)} relevant code sections for: {payload.query}",
            "context_items": context_items,
        },
    )
