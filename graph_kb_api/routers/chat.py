"""
Chat/LLM router.

Provides endpoints for LLM-powered code Q&A with source references
and optional Server-Sent Events streaming.

The /ask/stream endpoint uses the LangGraph AskCodeWorkflowEngine which provides:
- Multi-hop graph traversal for comprehensive context
- Tool calling for additional searches when needed
- Progress steps visible to the user
- Iterative agent reasoning
"""

import json
import logging
import re
import uuid
from typing import Any, AsyncGenerator, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.schemas.chat import (
    AskCodeRequest,
    AskCodeResponse,
    SourceItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

_SYSTEM_PROMPT = (
    "You are a code analysis assistant. Answer the user's question about their "
    "codebase using the provided context. Include code snippets and file references "
    "where relevant. If you need to illustrate architecture or relationships, use "
    "Mermaid diagram blocks (```mermaid ... ```). If the provided context is "
    "insufficient, say so honestly.\n\n"
    "## Mermaid Diagram Rules (IMPORTANT)\n"
    "When generating Mermaid diagrams you MUST follow these rules so the diagram "
    "renders correctly in the browser:\n"
    "1. **Quote node labels** that contain special characters. Use double-quotes "
    'around the label text: `A["my label (details)"]`\n'
    "2. **No HTML tags** — never use `<br/>`, `<br>`, or any HTML inside labels. "
    "Use `\\n` for line breaks inside quoted labels, e.g. "
    '`A["Line one\\nLine two"]`\n'
    "3. **Escape parentheses** — bare `(` `)` inside `[]` labels break parsing. "
    'Always quote: `A["scripts/ (maintenance tooling)"]`\n'
    "4. **Subgraph syntax** — when using subgraphs with titles, add a SPACE before "
    'the bracket: `subgraph ID ["Title"]` NOT `subgraph ID["Title"]`\n'
    "5. **Keep it simple** — prefer `flowchart TD` or `graph TD`. Avoid advanced "
    "features like `subgraph` nesting beyond one level.\n"
    "6. **No trailing arrows** — every `-->` must connect two nodes.\n"
    "7. **Valid identifiers** — node IDs must be alphanumeric (A-Z, a-z, 0-9, _). "
    "Put everything else in the quoted label.\n"
    "8. **No escaped quotes inside labels** — never use `\\\"` inside `[\"...\"]`. "
    "Mermaid doesn't support backslash-escaped quotes. Use `#quot;` entity or omit "
    'inner quotes: `A["model: name"]` NOT `A["model \\"name\\""]`.\n'
)


def extract_mermaid_diagrams(text: str) -> List[str]:
    """Parse mermaid code fence blocks from text.

    Returns a list of the raw mermaid diagram strings (without the
    fence markers).
    """
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
    return [m.group(1).strip() for m in pattern.finditer(text)]


def _build_llm_prompt(query: str, context_items) -> str:
    """Build the user prompt with retrieved context."""
    parts = ["## Retrieved Code Context\n"]
    for item in context_items:
        header = item.file_path or item.symbol or "context"
        if item.start_line and item.end_line:
            header += f" (lines {item.start_line}-{item.end_line})"
        parts.append(f"### {header}\n```\n{item.content or ''}\n```\n")
    parts.append(f"## Question\n{query}")
    return "\n".join(parts)


def _context_items_to_sources(context_items) -> List[SourceItem]:
    """Convert retrieval context items to SourceItem schemas."""
    sources = []
    for item in context_items:
        if item.file_path:
            sources.append(
                SourceItem(
                    file_path=item.file_path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    content=item.content,
                    symbol=item.symbol,
                    score=item.score,
                )
            )
    return sources


def _get_llm(facade):
    """Instantiate and return the LLM service.

    Raises HTTPException(502) if the LLM cannot be created.
    """
    try:
        from graph_kb_api.core.llm import LLMService

        logger.info("[CHAT] Creating LLMService instance...")
        svc = LLMService()
        logger.info("[CHAT] LLMService created successfully")
        return svc
    except Exception as exc:
        logger.error("[CHAT] Failed to initialise LLM service: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"LLM service is unreachable: {exc}",
        )


@router.post("/ask", response_model=AskCodeResponse)
async def ask_code(
    request: AskCodeRequest,
    facade=Depends(get_graph_kb_facade),
):
    """Answer a code question using retrieval + LLM.

    When ``repo_id`` is provided, retrieves context from the indexed
    repository before calling the LLM.  When omitted, routes through
    the NL handler (Deep Agent → Intent Detector → QA fallback) so
    the chat works without an ingested repository.
    """
    logger.info(
        "[CHAT] /ask request: repo_id=%s, query_len=%d",
        request.repo_id,
        len(request.query),
    )
    logger.info(
        "[CHAT] /ask endpoint called, query=%r, repo_id=%r",
        request.query,
        request.repo_id,
    )

    # --- No repo_id: use the NL routing chain (general QA) ---
    if not request.repo_id:
        logger.info("[CHAT] No repo_id provided, entering NL router path")
        try:
            from graph_kb_api.core.nl_router import get_natural_language_handler

            llm_service = _get_llm(facade)
            logger.info("[CHAT] LLM service created successfully for NL router path")
            handler = get_natural_language_handler(
                llm_service=llm_service, facade=facade
            )
            route_result = await handler.route(query=request.query, repo_id="")
            logger.info(
                "[CHAT] NL router returned response, length=%d",
                len(route_result.response),
            )
            mermaid_diagrams = extract_mermaid_diagrams(route_result.response)
            return AskCodeResponse(
                answer=route_result.response,
                sources=[],
                mermaid_diagrams=mermaid_diagrams,
                model=getattr(llm_service.llm, "model_name", None),
                intent=route_result.intent,
            )
        except Exception as exc:
            logger.error("[CHAT] NL router failed: %s", exc, exc_info=True)
            # Last-resort: direct LLM call without context
            llm_service = _get_llm(facade)
            try:
                answer = await llm_service.a_generate_response(
                    _SYSTEM_PROMPT,
                    f"The user has not selected a repository. Answer their general question:\n\n{request.query}",
                )
                return AskCodeResponse(
                    answer=answer,
                    sources=[],
                    mermaid_diagrams=extract_mermaid_diagrams(answer),
                    model=getattr(llm_service.llm, "model_name", None),
                )
            except Exception as llm_exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"LLM API is unreachable: {llm_exc}",
                )

    # --- repo_id provided: standard retrieval + LLM flow ---
    logger.info(
        "[CHAT] repo_id provided (%s), entering retrieval + LLM path", request.repo_id
    )
    retrieval_service = facade.retrieval_service
    if retrieval_service is None:
        raise HTTPException(
            status_code=503,
            detail="Retrieval service is unavailable",
        )

    # Step 1: Retrieve context
    try:
        from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

        config = RetrievalConfig(top_k_vector=request.top_k)
        result = retrieval_service.retrieve(
            repo_id=request.repo_id,
            query=request.query,
            config=config,
        )
        context_items = result.context_items
        logger.info("[CHAT] Retrieval returned %d context items", len(context_items))
    except Exception as exc:
        logger.error("[CHAT] Retrieval failed: %s", exc, exc_info=True)
        context_items = []

    sources = _context_items_to_sources(context_items)

    # Generate workflow_id for sources caching
    workflow_id = str(uuid.uuid4())

    # If no context was found, acknowledge it
    if not context_items:
        return AskCodeResponse(
            answer=(
                "I couldn't find any relevant code context for your query. "
                "The repository may not be indexed yet, or the query may not "
                "match any indexed content. Please try rephrasing your question "
                "or ensure the repository has been ingested."
            ),
            sources=[],
            mermaid_diagrams=[],
            workflow_id=workflow_id,
        )

    # Step 2: Call LLM
    llm_service = _get_llm(facade)
    logger.info("[CHAT] LLM service created for retrieval path")
    user_prompt = _build_llm_prompt(request.query, context_items)

    try:
        answer = await llm_service.a_generate_response(_SYSTEM_PROMPT, user_prompt)
        logger.info("[CHAT] LLM response received, length=%d", len(answer))
    except Exception as exc:
        logger.error("[CHAT] LLM call failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"LLM API is unreachable: {exc}",
        )

    mermaid_diagrams = extract_mermaid_diagrams(answer)

    # Cache sources for the sources page
    from graph_kb_api.flows.v3.utils.sources_cache import sources_cache
    sources_cache.store(
        workflow_id=workflow_id,
        sources=[s.model_dump() for s in sources],
        total_count=len(sources),
        repo_id=request.repo_id or "",
        query=request.query,
    )

    return AskCodeResponse(
        answer=answer,
        sources=sources,
        mermaid_diagrams=mermaid_diagrams,
        model=getattr(llm_service.llm, "model_name", None),
        workflow_id=workflow_id,
    )


async def _stream_sse(
    request: AskCodeRequest,
    facade,
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a streaming code Q&A response.

    DEPRECATED: This function is kept as a fallback when the LangGraph
    workflow engine is unavailable. Use _stream_sse_with_workflow instead.
    """

    logger.info(
        "[CHAT] /ask/stream request: repo_id=%s, query_len=%d",
        request.repo_id,
        len(request.query),
    )

    # --- No repo_id: general QA without retrieval ---
    if not request.repo_id:
        logger.info("[CHAT] No repo_id — using direct LLM streaming")
        try:
            from graph_kb_api.core.llm import LLMService

            llm_service = LLMService()
        except Exception as exc:
            logger.error("[CHAT] LLMService creation failed: %s", exc, exc_info=True)
            error_event = {
                'type': 'error',
                'error': str(exc),
                'message': f"LLM service is unreachable: {exc}",
            }
            yield f"data: {json.dumps(error_event)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"

        system_prompt = (
            "You are a helpful code assistant. The user has not selected a "
            "specific repository. Answer their question to the best of your "
            "ability. If the question requires repository context, let them "
            "know they can select one for more specific answers.\n\n"
            "## Mermaid Diagram Rules\n"
            "When generating Mermaid diagrams:\n"
            '- Quote labels with special chars: A["label (info)"]\n'
            "- No HTML tags (<br/> etc.) — use \\n inside quoted labels\n"
            "- Node IDs must be alphanumeric; put everything else in the label\n"
            "- Every --> must connect two nodes\n"
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=request.query),
        ]

        full_answer = ""
        chunk_count = 0
        try:
            logger.info("[CHAT] Starting LLM astream (no repo)...")
            async for chunk in llm_service.llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_answer += token
                    chunk_count += 1
                    yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"
            logger.info(
                "[CHAT] LLM stream complete: %d chunks, %d chars",
                chunk_count,
                len(full_answer),
            )
        except Exception as exc:
            logger.error("[CHAT] LLM streaming failed: %s", exc, exc_info=True)
            error_event = {
                'type': 'error',
                'error': str(exc),
                'message': f"LLM API error: {exc}",
            }
            yield f"data: {json.dumps(error_event)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
            return

        mermaid_diagrams = extract_mermaid_diagrams(full_answer)
        if mermaid_diagrams:
            yield f"data: {json.dumps({'type': 'mermaid', 'diagrams': mermaid_diagrams})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    # --- repo_id provided: standard retrieval + streaming LLM ---
    logger.info("[CHAT] repo_id=%s — using retrieval + LLM streaming", request.repo_id)
    retrieval_service = facade.retrieval_service
    if retrieval_service is None:
        logger.error("[CHAT] Retrieval service is unavailable")
        error_event = {
            'type': 'error',
            'error': 'retrieval_unavailable',
            'message': "Retrieval service is unavailable",
        }
        yield f"data: {json.dumps(error_event)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
        return

    # Retrieve context
    try:
        from graph_kb_api.graph_kb.models.retrieval import RetrievalConfig

        config = RetrievalConfig(top_k_vector=request.top_k)
        result = retrieval_service.retrieve(
            repo_id=request.repo_id,
            query=request.query,
            config=config,
        )
        context_items = result.context_items
        logger.info("[CHAT] Retrieved %d context items", len(context_items))
    except Exception as exc:
        logger.error("[CHAT] Retrieval failed during stream: %s", exc, exc_info=True)
        context_items = []

    sources = _context_items_to_sources(context_items)

    # Send sources as the first event
    sources_data = [s.model_dump(exclude_none=True) for s in sources]
    yield f"data: {json.dumps({'type': 'sources', 'sources': sources_data})}\n\n"

    if not context_items:
        no_ctx_msg = (
            "I couldn't find any relevant code context for your query. "
            "The repository may not be indexed yet, or the query may not "
            "match any indexed content."
        )
        yield f"data: {json.dumps({'type': 'chunk', 'content': no_ctx_msg})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    # Stream LLM response
    try:
        from graph_kb_api.core.llm import LLMService

        llm_service = LLMService()
    except Exception as exc:
        logger.error("[CHAT] LLMService creation failed: %s", exc, exc_info=True)
        error_event = {
            'type': 'error',
            'error': str(exc),
            'message': f"LLM service is unreachable: {exc}",
        }
        yield f"data: {json.dumps(error_event)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
        return

    user_prompt = _build_llm_prompt(request.query, context_items)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    full_answer = ""
    chunk_count = 0
    try:
        logger.info("[CHAT] Starting LLM astream (with repo)...")
        async for chunk in llm_service.llm.astream(messages):
            token = chunk.content if hasattr(chunk, "content") else str(chunk)
            if token:
                full_answer += token
                chunk_count += 1
                yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"
        logger.info(
            "[CHAT] LLM stream complete: %d chunks, %d chars",
            chunk_count,
            len(full_answer),
        )
    except Exception as exc:
        logger.error("[CHAT] LLM streaming failed: %s", exc, exc_info=True)
        error_event = {
            'type': 'error',
            'error': str(exc),
            'message': f"LLM API error: {exc}",
        }
        yield f"data: {json.dumps(error_event)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
        return

    # Send mermaid diagrams extracted from the full answer
    mermaid_diagrams = extract_mermaid_diagrams(full_answer)
    if mermaid_diagrams:
        yield f"data: {json.dumps({'type': 'mermaid', 'diagrams': mermaid_diagrams})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# Node-to-phase map for LangGraph workflow streaming progress
# Keys are the actual node names from AskCodeWorkflowEngine's _compile_workflow()
_ASK_CODE_NODE_PHASES: Dict[str, str] = {
    "validate": "Validating input",
    "analyze_question": "Analyzing question",
    "clarify": "Requesting clarification",
    "retrieve": "Searching code",
    "graph_expansion": "Exploring code relationships",
    "agent": "Agent reasoning",
    "tools": "Executing tool calls",
    "format": "Formatting response",
    "present": "Presenting results",
}


async def _stream_sse_with_workflow(
    request: AskCodeRequest,
    facade,
) -> AsyncGenerator[str, None]:
    """Stream an LLM-powered code Q&A response using the LangGraph workflow.

    This function uses the AskCodeWorkflowEngine which provides:
    - Multi-hop graph traversal for comprehensive context
    - Tool calling for additional searches when needed
    - Progress steps visible to the user
    - Iterative agent reasoning

    Yields SSE events with the following types:
    - 'progress': Workflow step progress updates (including granular retrieval progress)
    - 'sources': Retrieved code sources
    - 'chunk': LLM response tokens
    - 'mermaid': Mermaid diagrams extracted from the response
    - 'done': Stream completion signal
    """
    import asyncio

    from graph_kb_api.flows.v3.utils.progress_queue import ProgressQueue

    workflow_id = str(uuid.uuid4())[:8]
    logger.info(
        "[CHAT] /ask/stream workflow request: repo_id=%s, query_len=%d, workflow_id=%s",
        request.repo_id,
        len(request.query),
        workflow_id,
    )

    # --- No repo_id: general QA without retrieval ---
    if not request.repo_id:
        logger.info("[CHAT] No repo_id — falling back to direct LLM streaming")
        async for event in _stream_sse(request, facade):
            yield event
        return

    # --- Try to use the LangGraph workflow engine ---
    try:
        from graph_kb_api.context import get_app_context
        from graph_kb_api.flows.v3.graphs.ask_code import AskCodeWorkflowEngine

        app_context = get_app_context()

        logger.info(
            "[CHAT] Initializing AskCodeWorkflowEngine | workflow_id=%s repo_id=%s",
            workflow_id,
            request.repo_id,
        )

        # Create progress queue for granular updates during retrieval
        progress_queue = ProgressQueue()

        # Create the workflow engine
        engine = AskCodeWorkflowEngine(
            llm=app_context.llm,
            app_context=app_context,
            checkpointer=None,  # No checkpointing for stateless HTTP
            use_default_checkpointer=False,
        )

        # Track progress and accumulate state
        nodes_completed = 0
        total_nodes = len(_ASK_CODE_NODE_PHASES)
        final_state: Dict[str, Any] = {}
        workflow_done = False

        # Send initial progress event
        yield f"data: {json.dumps({'type': 'progress', 'step': 'initializing', 'phase': 'initializing', 'progress_percent': 0, 'message': 'Starting code analysis...', 'current_step': 1, 'total_steps': 8})}\n\n"

        # Create async queue consumer task
        async def consume_progress_queue():
            """Consume progress events from the queue and yield them."""
            async for event in progress_queue:
                yield f"data: {json.dumps(event.to_dict())}\n\n"

        # Stream the workflow execution
        # Pass args in the format expected by ValidateInputNode: [repo_id, query]
        # Include app_context and progress_queue in config so nodes can access it
        config = {
            "configurable": {
                "services": {
                    "app_context": app_context,
                    "progress_queue": progress_queue,
                }
            }
        }

        # Create workflow streaming task
        async def run_workflow():
            """Run the workflow and collect results."""
            nonlocal workflow_done, nodes_completed, final_state
            try:
                async for chunk in engine.start_workflow_stream(
                    user_query=request.query,
                    user_id="http-user",
                    session_id=workflow_id,
                    config=config,
                    repo_id=request.repo_id,
                    args=[request.repo_id, request.query],  # For ValidateInputNode
                    original_question=request.query,
                    refined_question=request.query,
                ):
                    for node_name, state_update in chunk.items():
                        if node_name == "__end__":
                            continue

                        nodes_completed += 1
                        phase = _ASK_CODE_NODE_PHASES.get(node_name, node_name)
                        progress_pct = min((nodes_completed / total_nodes) * 100, 100)

                        # Send progress event
                        progress_event = {
                            'type': 'progress',
                            'step': node_name,
                            'phase': phase,
                            'progress_percent': round(progress_pct, 1),
                            'message': f"{phase}...",
                            'node': node_name,
                            'nodes_completed': nodes_completed,
                            'total_nodes': total_nodes,
                            'current_step': nodes_completed,
                            'total_steps': total_nodes,
                        }
                        yield f"data: {json.dumps(progress_event)}\n\n"

                        # Merge state updates
                        if state_update:
                            final_state.update(state_update)
            finally:
                workflow_done = True
                progress_queue.close()

        # Run workflow and yield events concurrently using asyncio.Queue
        event_queue: asyncio.Queue = asyncio.Queue()

        async def collect_workflow_events():
            """Collect workflow events and put them in the event queue."""
            try:
                async for event in run_workflow():
                    await event_queue.put(('workflow', event))
            finally:
                await event_queue.put(('workflow_done', None))

        async def collect_queue_events():
            """Collect progress queue events and put them in the event queue."""
            try:
                async for event in consume_progress_queue():
                    await event_queue.put(('progress', event))
            finally:
                await event_queue.put(('progress_done', None))

        # Start both collectors as background tasks
        workflow_task = asyncio.create_task(collect_workflow_events())
        progress_task = asyncio.create_task(collect_queue_events())

        workflow_done_flag = False
        progress_done_flag = False

        # Yield events from the queue as they arrive
        while not (workflow_done_flag and progress_done_flag):
            try:
                source, event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                if source == 'workflow_done':
                    workflow_done_flag = True
                elif source == 'progress_done':
                    progress_done_flag = True
                elif event:
                    yield event
            except asyncio.TimeoutError:
                # Send keepalive if no events for 30 seconds
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

        # Wait for tasks to complete
        await asyncio.gather(workflow_task, progress_task, return_exceptions=True)

        # Extract results from final state
        context_items = final_state.get('context_items', [])
        llm_response = final_state.get('llm_response', '') or final_state.get('final_output', '')
        tool_calls_history = final_state.get('tool_calls_history', [])

        # Send sources event (limited to 20 for display, include total count)
        sources = _context_items_to_sources(context_items) if context_items else []
        total_sources = len(sources)
        displayed_sources = sources[:20]
        sources_data = [s.model_dump(exclude_none=True) for s in displayed_sources]

        # Store all sources in cache for the sources page
        if total_sources > 20:
            from graph_kb_api.flows.v3.utils.sources_cache import sources_cache
            all_sources_data = [s.model_dump(exclude_none=True) for s in sources]
            sources_cache.store(
                workflow_id=workflow_id,
                sources=all_sources_data,
                total_count=total_sources,
                repo_id=request.repo_id or 'unknown',
                query=request.query,
            )

        yield f"data: {json.dumps({'type': 'sources', 'sources': sources_data, 'total_sources': total_sources, 'tool_calls': len(tool_calls_history), 'workflow_id': workflow_id})}\n\n"

        # If we have a response, stream it as chunks
        if llm_response:
            # Send the response in chunks to simulate streaming
            chunk_size = 50  # Characters per chunk
            for i in range(0, len(llm_response), chunk_size):
                token = llm_response[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"

        # Send mermaid diagrams if any
        mermaid_diagrams = extract_mermaid_diagrams(llm_response)
        if mermaid_diagrams:
            yield f"data: {json.dumps({'type': 'mermaid', 'diagrams': mermaid_diagrams})}\n\n"

        logger.info(
            "[CHAT] Workflow complete | workflow_id=%s nodes=%d context_items=%d tool_calls=%d response_len=%d",
            workflow_id,
            nodes_completed,
            len(context_items),
            len(tool_calls_history),
            len(llm_response),
        )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except ImportError as e:
        logger.warning(
            "[CHAT] AskCodeWorkflowEngine not available (%s), falling back to direct retrieval | workflow_id=%s",
            e,
            workflow_id,
        )
        async for event in _stream_sse(request, facade):
            yield event
        return

    except TypeError as e:
        logger.warning(
            "[CHAT] AskCodeWorkflowEngine initialization failed (%s), falling back to direct retrieval | workflow_id=%s",
            e,
            workflow_id,
        )
        async for event in _stream_sse(request, facade):
            yield event
        return

    except Exception as e:
        logger.error(
            "[CHAT] Workflow error: %s | workflow_id=%s",
            e,
            workflow_id,
            exc_info=True,
        )
        # Send dedicated error event so frontend can handle it properly
        error_event = {
            'type': 'error',
            'error': str(e),
            'message': f"An error occurred during analysis: {str(e)}",
            'workflow_id': workflow_id,
        }
        yield f"data: {json.dumps(error_event)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
        return


@router.post("/ask/stream")
async def ask_code_stream(
    request: AskCodeRequest,
    facade=Depends(get_graph_kb_facade),
):
    """Stream an LLM-powered code Q&A response via Server-Sent Events.

    This endpoint uses the LangGraph AskCodeWorkflowEngine which provides:
    - Multi-hop graph traversal for comprehensive context
    - Tool calling for additional searches when needed
    - Progress steps visible to the user
    - Iterative agent reasoning
    """
    logger.info("[CHAT] /ask/stream endpoint called")
    logger.info(
        "[CHAT] /ask/stream endpoint called, query=%r, repo_id=%r",
        request.query,
        request.repo_id,
    )
    return StreamingResponse(
        _stream_sse_with_workflow(request, facade),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
