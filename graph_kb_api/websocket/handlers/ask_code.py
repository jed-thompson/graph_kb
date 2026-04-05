"""
Ask-code workflow handler.

Handles code analysis and question-answering workflows over WebSocket.
"""

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.websocket.handlers.base import (
    ASK_CODE_NODE_PHASES,
    logger,
)
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.progress import stream_workflow_with_progress
from graph_kb_api.websocket.protocol import AskCodePayload

# Workflow type to intent mapping for progress events
WORKFLOW_TYPE_TO_INTENT = {
    "ask-code": "ask_code",
    "deep": "deep_analysis",
    "ingest": "ingest_repo",
    "multi_agent": "multi_agent",
}


async def handle_ask_code_workflow(
    client_id: str,
    workflow_id: str,
    payload: AskCodePayload,
) -> None:
    """Handle the ask-code workflow with WebSocket progress callbacks."""
    try:
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "step": "initializing",
                "phase": "initializing",
                "progress_percent": -1,
                "message": "Starting code analysis...",
                "intent": "ask_code",
            },
        )

        from graph_kb_api.context import get_app_context

        app_context = get_app_context()

        try:
            from graph_kb_api.flows.v3.graphs.ask_code import AskCodeWorkflowEngine

            engine = AskCodeWorkflowEngine(
                llm=app_context.llm,
                app_context=app_context,
                checkpointer=None,
                use_default_checkpointer=False,
            )

            result = await stream_workflow_with_progress(
                engine=engine,
                client_id=client_id,
                workflow_id=workflow_id,
                manager=manager,
                query=payload.query,
                repo_id=payload.repo_id,
                node_phase_map=ASK_CODE_NODE_PHASES,
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
            logger.warning(f"AskCodeWorkflowEngine not available: {e}")
            facade = get_graph_kb_facade()
            await _fallback_ask_code(client_id, workflow_id, payload, facade)

    except Exception as e:
        logger.error(f"Ask-code workflow error: {e}", exc_info=True)
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={"message": str(e), "code": "WORKFLOW_ERROR"},
        )
    finally:
        await manager.complete_workflow(workflow_id)


async def _fallback_ask_code(
    client_id: str,
    workflow_id: str,
    payload: AskCodePayload,
    facade,
) -> None:
    """Fallback ask-code using retrieval service directly."""
    progress = manager.create_progress_callback(client_id, workflow_id)
    await progress("retrieving", message="Searching code...")

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
            "response": f"Found {len(context_items)} relevant code sections for: {payload.query}",
            "context_items": context_items,
        },
    )
