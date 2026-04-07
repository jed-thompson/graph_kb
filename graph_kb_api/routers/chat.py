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

import asyncio
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


_MULTI_REPO_SYSTEM_PROMPT = (
    "You are a senior software architect with deep expertise in distributed systems and "
    "multi-service codebases. You are answering questions that span multiple code repositories.\n\n"
    "## Your primary job\n"
    "Reason *across* the provided repositories, not about each one in isolation. "
    "The user wants to understand how these services interact, share data, or diverge in approach.\n\n"
    "## What to look for when answering\n"
    "When the question is about communication or integration between services, actively search the "
    "provided context for:\n"
    "- **HTTP/REST clients**: `requests`, `httpx`, `axios`, `fetch`, base URLs, route paths\n"
    "- **gRPC stubs**: `Stub(channel)`, `grpc.insecure_channel`, `.proto` service definitions, "
    "generated `*_pb2_grpc.py` files\n"
    "- **Message queues / events**: topic names, `publish`, `subscribe`, `consumer_group`, "
    "SQS/Kafka/PubSub client calls\n"
    "- **Shared contracts**: protobuf imports, shared model packages, OpenAPI client generation\n"
    "- **Environment / config wiring**: env vars like `*_URL`, `*_HOST`, `*_TOPIC` that point "
    "one service at another\n\n"
    "## How to structure your answer\n"
    "1. **State what you found** — cite specific files, functions, and line ranges from the context.\n"
    "2. **State what is missing** — if call-site code, proto definitions, or config wiring was "
    "not retrieved, say so explicitly and describe what file types would contain it.\n"
    "3. **Cross-reference across repos** — if repo A publishes an event and repo B consumes one, "
    "connect them even if they are in separate context sections.\n"
    "4. **Name repos explicitly** — always use the repository name when attributing a finding, "
    "never just 'the service'.\n"
    "5. **Diagrams when useful** — use a Mermaid diagram to show service topology or data flow "
    "when prose alone would be confusing.\n\n"
    "## Mermaid Diagram Rules\n"
    'Quote node labels with special characters: `A["label (detail)"]`\n'
    "No HTML tags — use `\\n` inside quoted labels for line breaks.\n"
    "Node IDs must be alphanumeric. Every `-->` must connect two nodes.\n"
    'Subgraph titles need a space: `subgraph ID ["Title"]`\n'
)


def _build_multi_repo_prompt(query: str, context_items: List[Any], repo_ids: List[str]) -> str:
    """Build a user prompt for multi-repo questions.

    Groups retrieved context by repository so the LLM can reason across service
    boundaries. Surfaces the full repo inventory and flags when inter-service
    wiring artefacts (clients, protos, env config) were not retrieved.
    """
    # Group items by repo_id
    by_repo: Dict[str, List[Any]] = {r: [] for r in repo_ids}
    for item in context_items:
        repo_id = item.get("_repo_id", "") if isinstance(item, dict) else ""
        if repo_id in by_repo:
            by_repo[repo_id].append(item)

    parts: List[str] = [
        "## Repositories in scope\n"
        + "\n".join(f"- `{r}`" for r in repo_ids)
        + "\n"
    ]

    for repo_id in repo_ids:
        items = by_repo.get(repo_id, [])
        parts.append(f"\n---\n## Repository: `{repo_id}`\n")
        if not items:
            parts.append("_No context retrieved for this repository._\n")
            continue
        for item in items:
            file_path = item.get("file_path", "") if isinstance(item, dict) else (getattr(item, "file_path", "") or "")
            content = item.get("content", "") if isinstance(item, dict) else (getattr(item, "content", "") or "")
            start_line = item.get("start_line") if isinstance(item, dict) else getattr(item, "start_line", None)
            end_line = item.get("end_line") if isinstance(item, dict) else getattr(item, "end_line", None)
            symbol = item.get("symbol") if isinstance(item, dict) else getattr(item, "symbol", None)

            header = file_path or symbol or "context"
            if start_line and end_line:
                header += f" (lines {start_line}–{end_line})"
            parts.append(f"### {header}\n```\n{content}\n```\n")

    parts.append(
        "\n---\n## Note on coverage\n"
        "The context above reflects the top similarity matches for the query. "
        "If you cannot find HTTP client calls, gRPC stubs, proto imports, queue topic names, "
        "or environment variable wiring in the context above, state that explicitly — "
        "those artefacts may not have been retrieved. Do not invent connections that are not "
        "evidenced in the provided code.\n"
    )

    parts.append(f"\n## Question\n{query}")
    return "\n".join(parts)


def _build_synthesis_prompt(
    query: str,
    successful: Dict[str, Dict[str, Any]],
    failed: List[str],
) -> str:
    """Build synthesis prompt combining per-repo agent analysis outputs."""
    parts = [
        "You are answering a question about multiple code repositories.\n"
        "Each section below contains a full analysis produced by a dedicated agent for one repository.\n"
        "Synthesize these analyses into a single, coherent answer.\n\n"
        "When comparing repositories, explicitly name each one. "
        "Do not repeat identical information — highlight similarities and differences. "
        "If repositories implement the same concept differently, explain each approach.\n\n"
        f"## Question\n{query}\n\n"
        "## Analysis per Repository\n",
    ]
    for repo_id, state in successful.items():
        output = state.get("final_output") or state.get("llm_response") or ""
        if len(output) > 8000:
            cutoff = output.rfind("\n", 0, 8000)
            cutoff = cutoff if cutoff > 0 else 8000
            output = output[:cutoff] + f"\n\n[... truncated — {len(output) - cutoff} characters omitted ...]"
        parts.append(f"\n### Repository: `{repo_id}`\n{output}\n")
    if failed:
        failed_list = ", ".join(f"`{r}`" for r in failed)
        parts.append(f"\n> **Note:** The following repositories could not be analysed: {failed_list}\n")
    parts.append(
        "\n## Synthesis Instructions\n"
        "Provide a unified answer that:\n"
        "1. Directly answers the question by drawing on all repositories above — do not treat each in isolation.\n"
        "2. Explicitly identifies inter-service communication: HTTP client calls, gRPC stubs, "
        "shared proto imports, message queue topic names, or environment variable wiring that "
        "connects one service to another. Cite the file and function where the call-site appears.\n"
        "3. If call-site code was not present in the per-repo analyses, say so clearly and name "
        "the file types or patterns that would contain it (e.g. `*_stub.py`, `*_client.py`, "
        "`settings.py` with `*_URL` variables, `.proto` service definitions).\n"
        "4. Compares or contrasts implementations where relevant, naming each repository explicitly.\n"
        "5. References specific files, functions, or line ranges found in each codebase.\n"
        "6. Uses a Mermaid service-topology diagram when it adds clarity that prose cannot provide.\n"
    )
    return "".join(parts)


def _context_items_to_sources(context_items) -> List[SourceItem]:
    """Convert retrieval context items to SourceItem schemas.

    Accepts either ContextItem dataclasses or dicts (state now stores dicts).
    """
    sources = []
    for item in context_items:
        file_path = item.get("file_path") if isinstance(item, dict) else item.file_path
        if file_path:
            sources.append(
                SourceItem(
                    file_path=file_path,
                    start_line=item.get("start_line") if isinstance(item, dict) else item.start_line,
                    end_line=item.get("end_line") if isinstance(item, dict) else item.end_line,
                    content=item.get("content") if isinstance(item, dict) else item.content,
                    symbol=item.get("symbol") if isinstance(item, dict) else item.symbol,
                    score=item.get("score") if isinstance(item, dict) else item.score,
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


async def _run_repo_workflow(
    repo_id: str,
    request: AskCodeRequest,
    app_context: Any,
    workflow_id: str,
    event_queue: asyncio.Queue,
    result_slot: Dict[str, Any],
) -> None:
    """Run the full AskCode workflow for a single repo.

    Pushes tagged SSE progress events onto event_queue and writes the
    completed final_state into result_slot[repo_id] when done.
    Always puts ('repo_done', repo_id) onto event_queue in the finally block.
    """
    from graph_kb_api.flows.v3.checkpointer import CheckpointerFactory
    from graph_kb_api.flows.v3.graphs.ask_code import AskCodeWorkflowEngine
    from graph_kb_api.flows.v3.utils.progress_queue import ProgressQueue

    total_nodes = len(_ASK_CODE_NODE_PHASES)
    nodes_completed = 0
    final_state: Dict[str, Any] = {}
    progress_queue = None
    workflow_task = None
    progress_task = None

    try:
        engine = AskCodeWorkflowEngine(
            llm=app_context.llm,
            app_context=app_context,
            checkpointer=CheckpointerFactory.create_checkpointer(),
            use_default_checkpointer=False,
        )
        progress_queue = ProgressQueue()

        config = {
            "configurable": {
                "thread_id": f"{workflow_id}_{repo_id}",
                "services": {
                    "app_context": app_context,
                    "progress_queue": progress_queue,
                },
            }
        }

        repo_event_queue: asyncio.Queue = asyncio.Queue()

        async def run_workflow_inner():
            nonlocal nodes_completed, final_state
            try:
                async for chunk in engine.start_workflow_stream(
                    user_query=request.query,
                    user_id="http-user",
                    session_id=workflow_id,
                    config=config,
                    repo_id=repo_id,
                    args=[repo_id, request.query],
                    original_question=request.query,
                    refined_question=request.query,
                ):
                    for node_name, state_update in chunk.items():
                        if node_name == "__end__":
                            continue
                        nodes_completed += 1
                        phase = _ASK_CODE_NODE_PHASES.get(node_name, node_name)
                        progress_pct = min((nodes_completed / total_nodes) * 100, 100)
                        progress_event = {
                            "type": "progress",
                            "step": f"{repo_id}::{node_name}",
                            "phase": phase,
                            "progress_percent": round(progress_pct, 1),
                            "message": f"[{repo_id}] {phase}...",
                            "repo_id": repo_id,
                            "node": node_name,
                            "nodes_completed": nodes_completed,
                            "total_nodes": total_nodes,
                            "current_step": nodes_completed,
                            "total_steps": total_nodes,
                        }
                        yield f"data: {json.dumps(progress_event)}\n\n"
                        if state_update:
                            final_state.update(state_update)
            finally:
                progress_queue.close()

        async def consume_progress_queue_inner():
            async for event in progress_queue:
                d = event.to_dict()
                d["repo_id"] = repo_id
                yield f"data: {json.dumps(d)}\n\n"

        async def collect_workflow_events_inner():
            try:
                async for event in run_workflow_inner():
                    await repo_event_queue.put(("workflow", event))
            finally:
                await repo_event_queue.put(("workflow_done", None))

        async def collect_queue_events_inner():
            try:
                async for event in consume_progress_queue_inner():
                    await repo_event_queue.put(("progress", event))
            finally:
                await repo_event_queue.put(("progress_done", None))

        workflow_task = asyncio.create_task(collect_workflow_events_inner())
        progress_task = asyncio.create_task(collect_queue_events_inner())

        workflow_done_flag = False
        progress_done_flag = False

        while not (workflow_done_flag and progress_done_flag):
            try:
                source, ev = await asyncio.wait_for(repo_event_queue.get(), timeout=30.0)
                if source == "workflow_done":
                    workflow_done_flag = True
                elif source == "progress_done":
                    progress_done_flag = True
                elif ev:
                    await event_queue.put(("sse", ev))
            except asyncio.TimeoutError:
                await event_queue.put(("sse", f"data: {json.dumps({'type': 'keepalive'})}\n\n"))

        await asyncio.gather(workflow_task, progress_task, return_exceptions=True)

        # Replace delta-accumulated state with the properly-reduced snapshot.
        # start_workflow_stream yields per-node deltas; shallow .update() loses
        # accumulated list fields (e.g. context_items overwritten by a later node).
        # get_workflow_state returns the fully-reduced LangGraph checkpoint.
        checkpointed = await engine.get_workflow_state(config)
        if checkpointed:
            final_state = checkpointed

    except Exception as exc:
        logger.error("[CHAT] Per-repo workflow failed for %s: %s", repo_id, exc, exc_info=True)
        if progress_queue is not None:
            progress_queue.close()
        for _t in [workflow_task, progress_task]:
            if _t is not None and not _t.done():
                _t.cancel()
    finally:
        result_slot[repo_id] = final_state if final_state else None
        await event_queue.put(("repo_done", repo_id))


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
    from graph_kb_api.flows.v3.utils.progress_queue import ProgressQueue

    workflow_id = str(uuid.uuid4())[:8]
    logger.info(
        "[CHAT] /ask/stream workflow request: repo_id=%s, query_len=%d, workflow_id=%s",
        request.repo_id,
        len(request.query),
        workflow_id,
    )

    # --- No repo_id: general QA without retrieval ---
    if not request.repo_id and not request.repo_ids:
        logger.info("[CHAT] No repo_id — falling back to direct LLM streaming")
        async for event in _stream_sse(request, facade):
            yield event
        return

    # --- Multi-repo: run full AskCode workflow per repo, then synthesize ---
    if request.repo_ids and len(request.repo_ids) >= 2:
        logger.info("[CHAT] Multi-repo full-workflow request: %s", request.repo_ids)
        try:
            from graph_kb_api.context import get_app_context
            from graph_kb_api.flows.v3.graphs.ask_code import AskCodeWorkflowEngine  # noqa: F401

            app_context = get_app_context()
        except Exception as e:
            logger.warning("[CHAT] AskCodeWorkflowEngine unavailable for multi-repo (%s), falling back", e)
            async for event in _stream_sse(request, facade):
                yield event
            return

        init_event = {
            "type": "progress",
            "step": "multi_repo_init",
            "phase": "Initializing",
            "progress_percent": 0,
            "message": f"Starting full analysis across {len(request.repo_ids)} repositories...",
            "current_step": 0,
            "total_steps": len(request.repo_ids) + 1,
        }
        yield f"data: {json.dumps(init_event)}\n\n"

        shared_event_queue: asyncio.Queue = asyncio.Queue()
        result_slot: Dict[str, Any] = {}
        repos_done: set = set()

        repo_tasks = [
            asyncio.create_task(
                _run_repo_workflow(
                    repo_id=repo_id,
                    request=request,
                    app_context=app_context,
                    workflow_id=workflow_id,
                    event_queue=shared_event_queue,
                    result_slot=result_slot,
                )
            )
            for repo_id in request.repo_ids
        ]

        while len(repos_done) < len(request.repo_ids):
            try:
                source, payload = await asyncio.wait_for(shared_event_queue.get(), timeout=30.0)
                if source == "repo_done":
                    repos_done.add(payload)
                    logger.info(
                        "[CHAT] Multi-repo: %s completed (%d/%d)",
                        payload, len(repos_done), len(request.repo_ids),
                    )
                elif source == "sse" and payload:
                    yield payload
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

        await asyncio.gather(*repo_tasks, return_exceptions=True)

        successful = {
            rid: state
            for rid, state in result_slot.items()
            if state and (state.get("final_output") or state.get("llm_response"))
        }
        failed = [rid for rid in request.repo_ids if rid not in successful]

        if failed:
            logger.warning("[CHAT] Multi-repo: %d/%d repos failed: %s", len(failed), len(request.repo_ids), failed)

        if not successful:
            all_failed_event = {"type": "error", "message": "All repository analyses failed. Please try again."}
            yield f"data: {json.dumps(all_failed_event)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
            return

        all_context_items: List = []
        for repo_id, state in successful.items():
            for item in state.get("context_items", []):
                tagged = dict(item) if isinstance(item, dict) else {
                    "file_path": item.file_path,
                    "content": item.content,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "symbol": item.symbol,
                }
                tagged["_repo_id"] = repo_id
                all_context_items.append(tagged)

        sources = _context_items_to_sources(all_context_items)
        total_sources = len(sources)
        sources_data = [s.model_dump(exclude_none=True) for s in sources[:20]]

        if total_sources > 20:
            from graph_kb_api.flows.v3.utils.sources_cache import sources_cache
            sources_cache.store(
                workflow_id=workflow_id,
                sources=[s.model_dump(exclude_none=True) for s in sources],
                total_count=total_sources,
                repo_id=",".join(request.repo_ids),
                query=request.query,
            )

        sources_event = {
            "type": "sources",
            "sources": sources_data,
            "total_sources": total_sources,
            "workflow_id": workflow_id,
        }
        yield f"data: {json.dumps(sources_event)}\n\n"

        synthesis_progress_event = {
            "type": "progress",
            "step": "synthesis",
            "phase": "Synthesizing cross-repo answer",
            "progress_percent": 95,
            "message": f"Synthesizing insights from {len(successful)} repositories...",
        }
        yield f"data: {json.dumps(synthesis_progress_event)}\n\n"

        synthesis_prompt = _build_synthesis_prompt(request.query, successful, failed)

        try:
            messages = [SystemMessage(content=_MULTI_REPO_SYSTEM_PROMPT), HumanMessage(content=synthesis_prompt)]
            full_answer = ""
            async for chunk in app_context.llm.llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_answer += token
                    yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"

            mermaid_diagrams = extract_mermaid_diagrams(full_answer)
            if mermaid_diagrams:
                yield f"data: {json.dumps({'type': 'mermaid', 'diagrams': mermaid_diagrams})}\n\n"

            total_tool_calls = sum(len(state.get("tool_calls_history", [])) for state in successful.values())
            logger.info(
                "[CHAT] Multi-repo complete | workflow_id=%s repos=%d context_items=%d tool_calls=%d response_len=%d",
                workflow_id, len(successful), len(all_context_items), total_tool_calls, len(full_answer),
            )
        except Exception as exc:
            logger.error("[CHAT] Multi-repo synthesis failed: %s", exc, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'error': True})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    # Normalize: single-item repo_ids — treat as a single-repo request so
    # ValidateInputNode receives a non-None repo_id.
    if request.repo_ids and len(request.repo_ids) == 1 and not request.repo_id:
        request = request.model_copy(update={"repo_id": request.repo_ids[0]})

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

        # Use the shared checkpointer so conversation history persists across
        # requests with the same conversation_id (thread_id).
        from graph_kb_api.flows.v3.checkpointer import CheckpointerFactory

        engine = AskCodeWorkflowEngine(
            llm=app_context.llm,
            app_context=app_context,
            checkpointer=CheckpointerFactory.create_checkpointer(),
            use_default_checkpointer=False,
        )

        # Track progress and accumulate state
        nodes_completed = 0
        total_nodes = len(_ASK_CODE_NODE_PHASES)
        final_state: Dict[str, Any] = {}
        workflow_done = False

        # Send initial progress event
        init_progress_event = {
            "type": "progress",
            "step": "initializing",
            "phase": "initializing",
            "progress_percent": 0,
            "message": "Starting code analysis...",
            "current_step": 1,
            "total_steps": 8,
        }
        yield f"data: {json.dumps(init_progress_event)}\n\n"

        # Create async queue consumer task
        async def consume_progress_queue():
            """Consume progress events from the queue and yield them."""
            async for event in progress_queue:
                yield f"data: {json.dumps(event.to_dict())}\n\n"

        # Stream the workflow execution
        # Pass args in the format expected by ValidateInputNode: [repo_id, query]
        # thread_id scopes the LangGraph checkpoint — same id = shared history.
        # Fall back to the ephemeral workflow_id if no conversation_id was sent.
        thread_id = request.conversation_id or workflow_id

        config = {
            "configurable": {
                "thread_id": thread_id,
                "services": {
                    "app_context": app_context,
                    "progress_queue": progress_queue,
                },
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
        if not tool_calls_history:
            # tool_calls_history is a LangGraph reducer field that may not survive dict.update()
            # accumulation; count ToolMessages from the message thread as the source of truth
            from langchain_core.messages import ToolMessage
            tool_calls_history = [m for m in final_state.get('messages', []) if isinstance(m, ToolMessage)]

        # Debug: Log what we extracted from final_state
        logger.info(
            "[CHAT] Extracted from final_state | llm_response_len=%d final_output_len=%d context_items=%d messages=%d",
            len(llm_response) if llm_response else 0,
            len(final_state.get('final_output', '')) if final_state.get('final_output') else 0,
            len(context_items),
            len(final_state.get('messages', [])),
        )

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

        single_repo_sources_event = {
            "type": "sources",
            "sources": sources_data,
            "total_sources": total_sources,
            "tool_calls": len(tool_calls_history),
            "workflow_id": workflow_id,
        }
        yield f"data: {json.dumps(single_repo_sources_event)}\n\n"

        # If we have a response, stream it as chunks
        if llm_response:
            # Send the response in chunks to simulate streaming
            chunk_size = 50  # Characters per chunk
            for i in range(0, len(llm_response), chunk_size):
                token = llm_response[i:i + chunk_size]
                yield f"data: {json.dumps({'type': 'chunk', 'content': token})}\n\n"
        else:
            # No response - send error message so frontend doesn't hang
            logger.error("[CHAT] No llm_response in final_state - workflow may have failed")
            error_msg = (
                "I encountered an issue generating a response. This might be because:\n\n"
                f"- The analysis workflow failed\n"
                f"- Too much context was retrieved ({len(context_items)} code chunks)\n"
                "- The LLM call timed out or exceeded token limits\n\n"
                "Try:\n"
                "- Starting a new conversation\n"
                "- Asking a more specific question\n"
                "- Focusing on a particular file or function"
            )
            for i in range(0, len(error_msg), 50):
                token = error_msg[i:i + 50]
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
            "[CHAT] AskCodeWorkflowEngine initialization failed (%s), "
            "falling back to direct retrieval | workflow_id=%s",
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
