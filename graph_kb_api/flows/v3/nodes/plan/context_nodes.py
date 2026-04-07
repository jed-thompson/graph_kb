"""Context subgraph nodes for the /plan command.

ValidateContextNode, CollectContextNode, ReviewNode, DeepAnalysisNode, FeedbackReviewNode.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Dict, List, cast

from langchain.messages import AIMessage

from graph_kb_api.flows.v3.agents import AgentResult

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

import httpx
from langgraph.types import RunnableConfig, interrupt
from markdownify import markdownify as md_to_md

from graph_kb_api.core.llm import LLMService
from graph_kb_api.database import AsyncMetadataService
from graph_kb_api.database.base import get_db_session_ctx
from graph_kb_api.database.document_models import UploadedDocument
from graph_kb_api.database.document_repositories import (
    DocumentLinkRepository,
    DocumentRepository,
)
from graph_kb_api.flows.v3.agents.context_review_agent import ContextReviewAgent
from graph_kb_api.flows.v3.agents.personas.prompt_manager import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import AgentTask, ThreadConfigurable
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard
from graph_kb_api.flows.v3.state import ContextData
from graph_kb_api.flows.v3.state.plan_state import (
    AnalysisReviewInterruptPayload,
    ArtifactRef,
    BudgetState,
    ContextSubgraphState,
    FormInterruptPayload,
)
from graph_kb_api.flows.v3.state.workflow_state import ContextRound, ReviewData
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt, sanitize_context_for_prompt
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator, truncate_to_tokens
from graph_kb_api.graph_kb.models import RepoMetadata
from graph_kb_api.storage.blob_storage import BlobStorage
from graph_kb_api.websocket.events import PhaseField
from graph_kb_api.websocket.plan_events import emit_phase_complete, emit_phase_progress

logger = logging.getLogger(__name__)


class ValidateContextNode(SubgraphAwareNode[ContextSubgraphState]):
    """Validates user-provided context before collection.

    Lightweight state validation that checks:
    - Context dict exists and is non-empty
    - session_id is present
    - If context has spec_name or user_explanation, mark valid

    No LLM calls - state-only access pattern (Pattern A).
    """

    def __init__(self) -> None:
        super().__init__(node_name="validate_context")
        self.phase = "context"
        self.step_name = "validate_context"
        self.step_progress = 0.0

    async def _execute_step(self, state: ContextSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        context: ContextData = state.get("context", {})
        session_id: str = state.get("session_id", "")

        validation_errors = []

        # Check session_id is present
        if not session_id:
            validation_errors.append(
                {
                    "field": "session_id",
                    "message": "session_id is required",
                    "severity": "error",
                }
            )

        # Check context dict exists and is non-empty
        if not context:
            # Empty context is acceptable for initial validation - will be collected
            return NodeExecutionResult.success(output={"context": {"validated": True, "is_empty": True}})

        # Validate required fields if context exists
        has_name = (
            bool(context.get("spec_name", "").strip())
            if isinstance(context.get("spec_name"), str)
            else bool(context.get("spec_name"))
        )
        has_explanation = (
            bool(context.get("user_explanation", "").strip())
            if isinstance(context.get("user_explanation"), str)
            else bool(context.get("user_explanation"))
        )

        if context and not has_name and not has_explanation:
            validation_errors.append(
                {
                    "field": "spec_name",
                    "message": "Either spec_name or user_explanation should be provided",
                    "severity": "warning",
                }
            )

        # Mark context as validated
        validated_context = {
            **context,
            "validated": True,
            "validation_errors": validation_errors,
        }

        return NodeExecutionResult.success(output={"context": validated_context})


class CollectContextNode(SubgraphAwareNode[ContextSubgraphState]):
    """Collects context from the codebase and user input."""

    def __init__(self) -> None:
        super().__init__(node_name="collect_context")
        self.phase = "context"
        self.step_name = "collect_context"
        self.step_progress = 0.25

    async def _execute_step(self, state: ContextSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        existing_context: Dict[str, Any] = {**state.get("context", {})}

        # Build repo selector options from indexed repos
        repo_options: List[Any] = [{"label": "None — no codebase context", "value": ""}]
        try:
            configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
            workflow_context: WorkflowContext | None = configurable.get("context")
            if workflow_context and workflow_context.graph_store is not None:
                async_store: AsyncMetadataService | None = workflow_context.graph_store.async_metadata_store
                if async_store:
                    repos: list[RepoMetadata] = await async_store.list_repos()
                    for r in repos:
                        repo_options.append(
                            {
                                "label": f"{r.git_url} ({r.default_branch})",
                                "value": r.repo_id,
                            }
                        )
        except Exception as e:
            logger.warning(f"CollectContextNode failed to fetch repos: {e}")

        context_fields = [
            PhaseField(
                id="spec_name",
                label="Specification name",
                type="text",
                required=True,
                placeholder="e.g. New Shipping Integration",
            ),
            PhaseField(
                id="spec_description",
                label="One-line description",
                type="textarea",
                required=True,
                placeholder="Brief summary of the feature",
            ),
            PhaseField(
                id="target_repo_id",
                label="Codebase repository (optional)",
                type="searchable_select",
                required=False,
                options=repo_options,
                placeholder="Search indexed repositories...",
            ),
            PhaseField(
                id="reference_urls",
                label="Reference URLs (optional)",
                type="url_list",
                required=False,
                placeholder="https://docs.example.com/spec",
            ),
            PhaseField(
                id="primary_document",
                label="Primary requirements document",
                type="file",
                required=False,
                placeholder="Paste or describe the primary requirements document",
            ),
            PhaseField(
                id="supporting_docs",
                label="Supporting documents & references",
                type="document_list",
                required=False,
                placeholder="Links, stakeholder input, additional docs",
            ),
            PhaseField(
                id="user_explanation",
                label="What are you building and why?",
                type="textarea",
                required=True,
                placeholder="Describe the feature, its goals, and motivation",
            ),
            PhaseField(
                id="constraints",
                label="Constraints (timeline, tech, budget)",
                type="textarea",
                required=False,
                placeholder="Technical and business constraints",
            ),
        ]

        payload: FormInterruptPayload = {
            "type": "form",
            "phase": "context",
            "step": "context_collection",
            "fields": [f.model_dump() for f in context_fields],
            "prefilled": {
                "spec_name": existing_context.get("spec_name", ""),
                "spec_description": existing_context.get("spec_description", ""),
                "target_repo_id": existing_context.get("target_repo_id", ""),
                "reference_urls": existing_context.get("reference_urls", []),
                "primary_document": existing_context.get("primary_document", ""),
                "user_explanation": existing_context.get("user_explanation", ""),
                "constraints": existing_context.get("constraints", ""),
                "supporting_docs": existing_context.get("supporting_docs", ""),
            },
        }
        user_input: Dict[str, Any] = interrupt(payload)

        merged_context = {**existing_context, **user_input}

        # Fetch reference URLs and store content for research phase
        urls = merged_context.get("reference_urls", [])
        if urls and isinstance(urls, (list, str)):
            if isinstance(urls, str):
                urls = [u.strip() for u in urls.split(",") if u.strip()]
            valid_urls = [u for u in urls if u.startswith("http")]
            if valid_urls:
                # Normalize to schema field name (extracted_urls)
                merged_context["extracted_urls"] = valid_urls
                try:
                    fetched_docs = await self._fetch_reference_urls(valid_urls)
                    if fetched_docs:
                        merged_context["reference_documents"] = fetched_docs
                except Exception as e:
                    logger.warning(f"CollectContextNode URL fetch failed: {e}")

        # Store scraped URL content as proper documents (blob + DB record + association)
        # Same pattern as file uploads in routers/plan.py:_upload_plan_document_impl
        fetched_docs = merged_context.get("reference_documents", [])
        session_id = state.get("session_id", "")
        url_meta_list: List[Dict[str, Any]] = []
        reference_doc_ids: List[str] = []

        if fetched_docs and session_id:
            try:
                storage: BlobStorage = BlobStorage.from_env()
                async with get_db_session_ctx() as db_session:
                    doc_repo = DocumentRepository(db_session)
                    assoc_repo = DocumentLinkRepository(db_session)

                    for i, doc in enumerate(fetched_docs):
                        url = doc.get("url", "")
                        content = doc.get("content", "")
                        if not content:
                            continue

                        content_bytes = content.encode("utf-8")
                        file_hash = hashlib.sha256(content_bytes).hexdigest()
                        doc_id = str(uuid.uuid4())
                        safe_name = self._url_to_safe_name(url, i)
                        storage_key = f"plan_docs/{session_id}/{doc_id}.md"

                        # Store blob
                        await storage.backend.store(
                            path=storage_key,
                            content=content_bytes,
                            content_type="text/markdown",
                        )

                        # Create document record
                        await doc_repo.create(
                            storage_key=storage_key,
                            original_filename=safe_name,
                            mime_type="text/markdown",
                            file_size=len(content_bytes),
                            uploaded_by="system",
                            storage_backend="local",
                            document_type="reference_url",
                            file_hash=file_hash,
                            metadata={"source_url": url},
                            document_id=doc_id,
                        )
                        await db_session.commit()

                        # Associate with plan session
                        await assoc_repo.associate(
                            source_type="plan_session",
                            source_id=session_id,
                            document_id=doc_id,
                            role="reference",
                            associated_by="system",
                            notes=f"Scraped from {url}",
                        )

                        summary = content.strip()
                        url_meta_list.append(
                            {
                                "url": url,
                                "document_id": doc_id,
                                "summary": summary,
                                "size_bytes": len(content_bytes),
                            }
                        )
                        reference_doc_ids.append(doc_id)
                        logger.info(
                            "CollectContextNode: stored reference doc %s from %s (size=%d)",
                            doc_id,
                            url,
                            len(content_bytes),
                        )

            except Exception as e:
                logger.warning("CollectContextNode failed to store reference documents: %s", e)

        if url_meta_list:
            merged_context["reference_urls_meta"] = url_meta_list
            merged_context.setdefault("supporting_doc_ids", []).extend(reference_doc_ids)
            logger.info(
                "CollectContextNode: set reference_urls_meta with %d entries, added %d doc IDs to supporting_doc_ids",
                len(url_meta_list),
                len(reference_doc_ids),
            )
        else:
            logger.warning(
                "CollectContextNode: no url_meta_list built — fetched_docs=%d, session_id=%s",
                len(fetched_docs),
                session_id,
            )

        # ── Step 3: Load document content + build composite section index ──
        from graph_kb_api.flows.v3.utils.document_content_reader import (
            PRIMARY_DOC_TOKEN_BUDGET,
            SUPPORTING_DOC_TOKEN_BUDGET,
            build_composite_document_index,
            build_section_index,
            format_documents_for_prompt,
            load_uploaded_document_contents,
        )

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")
        artifacts_output: Dict[str, Any] = {}

        # Resolve primary document ID.
        # CollectContextNode form field key is "primary_document";
        # FeedbackReviewNode normalizes to "primary_document_id" later.
        primary_id = merged_context.get("primary_document_id") or merged_context.get("primary_document") or ""
        if primary_id and not isinstance(primary_id, str):
            primary_id = str(primary_id)

        # Resolve supporting doc IDs (form field + URL-scraped references).
        supporting_ids: List[str] = list(merged_context.get("supporting_doc_ids") or [])
        form_supporting = merged_context.get("supporting_docs") or []
        if isinstance(form_supporting, str):
            form_supporting = [s.strip() for s in form_supporting.split(",") if s.strip()]
        for doc_id in form_supporting:
            if doc_id and doc_id not in supporting_ids:
                supporting_ids.append(doc_id)

        all_doc_entries: List[Dict[str, str]] = []

        # Load primary document content.
        if primary_id:
            try:
                primary_docs = await load_uploaded_document_contents(
                    [primary_id],
                    role="primary",
                    max_tokens_per_doc=PRIMARY_DOC_TOKEN_BUDGET,
                )
                all_doc_entries.extend(primary_docs)
                logger.info(
                    "CollectContextNode: loaded primary doc %s → %d entries",
                    primary_id,
                    len(primary_docs),
                )

                # Fallback: doc exists in ChromaDB (global docs) but not in the plan
                # document store. Fetch content directly from the vector store and
                # inject it so it's available to the LLM without requiring a DB write.
                if not primary_docs:
                    workflow_context = configurable.get("context")
                    vector_store = getattr(workflow_context, "vector_store", None) if workflow_context else None
                    if vector_store is not None:
                        try:
                            chunk = vector_store.get(primary_id)
                            if chunk and chunk.content:
                                filename = (chunk.metadata or {}).get("filename") or primary_id
                                all_doc_entries.append(
                                    {
                                        "doc_id": primary_id,
                                        "filename": filename,
                                        "content": chunk.content,
                                        "role": "primary",
                                    }
                                )
                                logger.info(
                                    "CollectContextNode: primary doc %s loaded from ChromaDB fallback (%d chars)",
                                    primary_id,
                                    len(chunk.content),
                                )
                            else:
                                logger.warning(
                                    "CollectContextNode: primary doc %s not found in ChromaDB fallback",
                                    primary_id,
                                )
                        except Exception as fallback_exc:
                            logger.warning(
                                "CollectContextNode: ChromaDB fallback failed for primary doc %s: %s",
                                primary_id,
                                fallback_exc,
                            )
                    else:
                        logger.warning(
                            "CollectContextNode: primary doc %s missing from plan store and no vector_store available",
                            primary_id,
                        )
            except Exception as e:
                logger.warning("CollectContextNode: failed to load primary doc %s: %s", primary_id, e)

        # Load supporting document content (4K token budget each).
        if supporting_ids:
            try:
                supporting_docs = await load_uploaded_document_contents(
                    supporting_ids,
                    role="supporting",
                    max_tokens_per_doc=SUPPORTING_DOC_TOKEN_BUDGET,
                )
                all_doc_entries.extend(supporting_docs)
                logger.info(
                    "CollectContextNode: loaded %d supporting docs → %d entries",
                    len(supporting_ids),
                    len(supporting_docs),
                )
            except Exception as e:
                logger.warning("CollectContextNode: failed to load supporting docs: %s", e)

        # Store document contents on context state.
        if all_doc_entries:
            merged_context["uploaded_document_contents"] = all_doc_entries

            # Build composite section index for all documents from their TRUNCATED string contents.
            # We will immediately overwrite the "sections" arrays using the FULL untruncated content.
            composite_index = build_composite_document_index(all_doc_entries)

            if artifact_svc:
                try:
                    async with get_db_session_ctx() as db_session:
                        doc_repo = DocumentRepository(db_session)
                        for i, idx_entry in enumerate(composite_index):
                            doc_id = idx_entry.get("doc_id")
                            if not doc_id:
                                continue

                            doc: UploadedDocument | None = await doc_repo.get(doc_id)
                            if not doc:
                                continue

                            raw_blob = await artifact_svc.blob.backend.retrieve(doc.storage_key)
                            full_content: str | None = None
                            if raw_blob and isinstance(raw_blob.content, str):
                                full_content = raw_blob.content
                            elif raw_blob and isinstance(raw_blob.content, bytes):
                                full_content = raw_blob.content.decode("utf-8", errors="replace")

                            if full_content:
                                # Rebuild doc's section index from full content (M1)
                                # so that start_char/end_char ranges match the full original spec.
                                full_sections = build_section_index(full_content, doc.original_filename)
                                composite_index[i]["sections"] = full_sections

                                # If this is the primary doc, store full primary spec in blob (M1)
                                if doc_id == primary_id:
                                    await artifact_svc.store(
                                        "context",
                                        "primary_spec_full.md",
                                        full_content,
                                        "Full primary spec for per-task section loading",
                                    )
                                    logger.info(
                                        "CollectContextNode: stored full primary spec (%d chars)"
                                        " at context/primary_spec_full.md",
                                        len(full_content),
                                    )
                except Exception as e:
                    logger.warning("CollectContextNode: failed to rebuild full document sections: %s", e)

            merged_context["document_section_index"] = composite_index
            logger.info(
                "CollectContextNode: built composite section index with %d document entries (full-content aligned)",
                len(composite_index),
            )

            # Store formatted docs as blob artifact at context.uploaded_docs.md.
            # FetchContextNode's existing artifact hydration loop auto-discovers
            # this via the "context.*" prefix match — zero changes needed there.
            if artifact_svc:
                # Budget includes all loaded docs (primary 8K + supporting 4K each) + 2K headroom (M3)
                doc_budget = PRIMARY_DOC_TOKEN_BUDGET + (SUPPORTING_DOC_TOKEN_BUDGET * len(supporting_ids)) + 2000
                formatted = format_documents_for_prompt(all_doc_entries, max_tokens=doc_budget)
                if formatted:
                    ref = await artifact_svc.store(
                        "context",
                        "uploaded_docs.md",
                        formatted,
                        "Formatted uploaded documents for task context injection",
                    )
                    artifacts_output["context.uploaded_docs"] = ref

                # Store composite section index (now containing FULL untruncated character ranges!)
                index_json = json.dumps(composite_index, default=str)
                ref: ArtifactRef = await artifact_svc.store(
                    "context",
                    "document_section_index.json",
                    index_json,
                    "Composite document section index for per-task loading",
                )
                artifacts_output["context.document_section_index"] = ref

        # Build return output — include artifacts if any were created.
        output_dict: Dict[str, Any] = {"context": merged_context}
        if artifacts_output:
            output_dict["artifacts"] = artifacts_output

        return NodeExecutionResult.success(output=output_dict)

    @staticmethod
    async def _fetch_reference_urls(urls: List[str]) -> List[Dict[str, str]]:
        """Fetch URLs and extract text content for context.

        Returns a list of dicts with 'url' and 'content' keys.
        """
        results: List[Dict[str, str]] = []
        logger.info("CollectContextNode: fetching %d reference URLs: %s", len(urls), urls)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for url in urls:
                try:
                    resp: httpx.Response = await client.get(url, headers={"User-Agent": "GraphKB/1.0"})
                    resp.raise_for_status()
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" in content_type:
                        text = md_to_md(resp.text, heading_style="ATX")
                    elif "text/plain" in content_type or "text/markdown" in content_type:
                        text = resp.text
                    else:
                        text = resp.text

                    logger.info(
                        "CollectContextNode: fetched url=%s status=%d content_type=%s text_len=%d",
                        url,
                        resp.status_code,
                        content_type,
                        len(text),
                    )
                    results.append({"url": url, "content": text})
                except Exception as e:
                    logger.warning(f"Failed to fetch reference URL {url}: {e}")
        return results

    @staticmethod
    def _url_to_safe_name(url: str, index: int) -> str:
        """Convert a URL to a safe blob storage name."""
        import re as _re

        stripped = _re.sub(r"^https?://", "", url).strip("/")
        safe = _re.sub(r"[^a-zA-Z0-9._-]", "_", stripped)[:80]
        return f"reference_{index}_{safe}.txt"


class ReviewNode(SubgraphAwareNode[ContextSubgraphState]):
    """AI review of collected context.

    Calls ContextReviewAgent.execute() to perform semantic analysis of
    the collected context, Identifies gaps, ambiguities, and generates
    clarification questions.
    """

    def __init__(self) -> None:
        super().__init__(node_name="review")
        self.phase = "context"
        self.step_name = "review"
        self.step_progress = 0.50

    async def _execute_step(self, state: ContextSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        budget: BudgetState = state.get("budget", {})
        context: ContextData = state.get("context", {})

        # Budget check before LLM call
        BudgetGuard.check(budget)

        # Instantiate and execute the context review agent
        client_id: str | None = configurable.get("client_id")
        agent = ContextReviewAgent(client_id=client_id)
        workflow_context = configurable.get("context")
        session_id = state.get("session_id", "")

        agent_task: AgentTask = {
            "description": "Context review analysis",
            "task_id": f"review_{session_id}",
            "context": cast(Dict[str, Any], context),
        }

        if not workflow_context:
            raise RuntimeError("ReviewNode requires workflow_context but none was provided")

        result: AgentResult = await agent.execute(
            task=agent_task,
            state=state,
            workflow_context=workflow_context,
        )

        # Propagate agent errors so SubgraphAwareNode emits spec.error to UI
        agent_error: str | None = result.get("error")
        if agent_error:
            raise RuntimeError(f"ContextReviewAgent failed: {agent_error}")

        # Decrement budget after LLM call
        tokens_used: int = get_token_estimator().count_tokens(str(result))
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=tokens_used)

        # Build review state output
        review_output = {
            "analysis": result.get("analysis_result", {}),
            "gaps": result.get("gaps_detected", {}),
            "clarification_questions": [
                {
                    "id": gap_value.get("id", f"question_{i}"),
                    "question": gap_value.get("question") or gap_value.get("title", ""),
                    "context": gap_value.get("context") or gap_value.get("description", ""),
                    "suggested_answers": gap_value.get("suggested_answers", []),
                }
                for i, (gap_key, gap_value) in enumerate(result.get("gaps_detected", {}).items())
                if isinstance(gap_value, dict)
            ],
            "approved": result.get("completeness_score", 0) >= 0.7,
            "completeness_score": result.get("completeness_score", 0.5),
            "summary": result.get("summary", ""),
            "suggested_actions": result.get("suggested_actions", []),
        }

        return NodeExecutionResult.success(
            output={
                "review": review_output,
                "budget": new_budget,
            }
        )


class DeepAnalysisNode(SubgraphAwareNode[ContextSubgraphState]):
    """Deep analysis of context via ResearchAgent.analyze_codebase().

    Calls the ResearchAgent's codebase analysis method to leverage
    graph KB queries for similar features and relevant modules,
    then enriches with LLM-driven architectural analysis.

    Stores full report via ArtifactService and returns ArtifactRef.
    """

    def __init__(self) -> None:
        super().__init__(node_name="deep_analysis")
        self.phase = "context"
        self.step_name = "deep_analysis"
        self.step_progress = 0.75

    async def _execute_step(self, state: ContextSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.agents.research_agent import ResearchAgent
        from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard

        context: ContextData = state.get("context", {})
        review: ReviewData = state.get("review", {})
        budget: BudgetState = state.get("budget", {})

        configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
        llm: LLMService | None = configurable.get("llm")
        artifact_svc: ArtifactService | None = configurable.get("artifact_service")

        BudgetGuard.check(budget)

        # Build the app_context adapter for the agent
        workflow_context = configurable.get("context")

        session_id = state.get("session_id", "")
        client_id = configurable.get("client_id")

        analysis_report: Dict[str, Any] = {}

        # Step 1: Call ResearchAgent.analyze_codebase() for graph KB data
        codebase_results: Dict[str, Any] = {}
        repo_id = context.get("target_repo_id", "")
        user_explanation = context.get("user_explanation", "")

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="context",
                step="deep_analysis",
                message="Analyzing codebase via graph KB",
                progress_pct=0.60,
                client_id=client_id,
            )
        except Exception as e:
            logger.warning(f"DeepAnalysisNode emit_phase_progress failed: {e}")

        try:
            if not workflow_context:
                raise RuntimeError("DeepAnalysisNode requires workflow_context for codebase analysis")
            research_agent = ResearchAgent(client_id=client_id)
            codebase_results = await research_agent.analyze_codebase(
                repo_id=repo_id,
                user_explanation=user_explanation,
                workflow_context=workflow_context,
            )
        except Exception as e:
            logger.warning(f"DeepAnalysisNode codebase analysis failed: {e}")

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase="context",
                step="deep_analysis",
                message="Running LLM-driven architectural analysis",
                progress_pct=0.70,
                client_id=client_id,
            )
        except Exception as e:
            logger.warning(f"DeepAnalysisNode emit_phase_progress failed: {e}")

        # Step 2: LLM-driven deep analysis enriched with codebase data
        if not llm:
            raise RuntimeError("DeepAnalysisNode requires an LLM but none was provided")

        context_json: str = json.dumps(sanitize_context_for_prompt(context), indent=2, default=str)
        review_json: str = json.dumps(review, indent=2, default=str)
        codebase_json: str = json.dumps(codebase_results, indent=2, default=str)

        # Truncate codebase_json to avoid exceeding LLM context limits

        codebase_json = truncate_to_tokens(codebase_json, 8000)

        base_prompt: str = get_agent_prompt_manager().get_prompt("context_deep_analysis", subdir="nodes")
        prompt = f"""{base_prompt}

## Context
```json
{context_json}
```

## Review Analysis
```json
{review_json}
```

## Codebase Analysis (from Graph KB)
```json
{codebase_json}
```
"""

        prompt = append_document_context_to_prompt(prompt, context)

        prompt += "\nPerform deep technical analysis of this specification."

        try:
            response: AIMessage = await asyncio.wait_for(llm.ainvoke(prompt), timeout=300)
        except asyncio.TimeoutError:
            raise RuntimeError(
                "DeepAnalysisNode LLM call timed out after 300s. The LLM provider may be experiencing high latency."
            )
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        analysis_report = self._parse_analysis_response(content)

        # Merge codebase results into the report
        if codebase_results:
            analysis_report["codebase_analysis"] = codebase_results

        # Store full report via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        context_output: Dict[str, Any] = {}

        if artifact_svc:
            report_json = json.dumps(analysis_report, indent=2, default=str)
            summary = analysis_report.get("summary", "Deep analysis report")
            ref = await artifact_svc.store(
                "context",
                "deep_analysis.json",
                report_json,
                summary,
            )
            artifacts_output["artifacts"] = {"context.deep_analysis": ref}
            context_output["context"] = {
                "deep_analysis_ref": ref,
                "deep_analysis_full": analysis_report,
            }
        else:
            context_output["context"] = {
                "deep_analysis": analysis_report.get("summary", ""),
                "deep_analysis_full": analysis_report,
            }

        tokens_used: int = get_token_estimator().count_tokens(content) if content else 0
        new_budget: BudgetState = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=tokens_used)

        return NodeExecutionResult.success(
            output={
                "budget": new_budget,
                **artifacts_output,
                **context_output,
            }
        )

    def _parse_analysis_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM response into structured analysis report."""
        try:
            import re

            json_match: re.Match[str] | None = re.search(r"\{[\s\S]*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, KeyError):
            pass
        return {
            "architecture_implications": {
                "systems_to_modify": [],
                "new_components_needed": [],
                "integration_points": [],
            },
            "risk_areas": [],
            "scope_boundaries": {"in_scope": [], "out_of_scope": [], "edge_cases": []},
            "technical_debt": [],
            "dependencies": {"external_systems": [], "libraries": [], "services": []},
            "summary": "Analysis completed (parsed from LLM response)",
        }


class FeedbackReviewNode(SubgraphAwareNode[ContextSubgraphState]):
    """HITL interrupt for reviewing LLM analysis and providing clarifications.

    Shows:
    - Completeness score from review
    - Detected gaps
    - Clarification questions for user to answer
    - Architectural analysis summary

    Collects:
    - Answers to clarification questions
    - Additional context from user
    - Acknowledgment of risks

    This node addresses the missing feedback review step between
    DeepAnalysisNode and ContextReviewGateNode.
    """

    def __init__(self) -> None:
        super().__init__(node_name="feedback_review")
        self.phase = "context"
        self.step_name = "feedback_review"
        self.step_progress = 0.90  # Before phase review gate

    @staticmethod
    def _to_camel_case(snake_str: str) -> str:
        """Convert snake_case to camelCase."""
        components = snake_str.split("_")
        return components[0] + "".join(x.title() for x in components[1:])

    @staticmethod
    def _normalize_keys(obj: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively normalize dict keys from snake_case to camelCase."""
        if not isinstance(obj, dict):
            return obj
        result: Dict[str, Any] = {}
        for key, value in obj.items():
            camel_key = FeedbackReviewNode._to_camel_case(key)
            if isinstance(value, dict):
                result[camel_key] = FeedbackReviewNode._normalize_keys(value)
            elif isinstance(value, list):
                result[camel_key] = [
                    FeedbackReviewNode._normalize_keys(item) if isinstance(item, dict) else item for item in value
                ]
            else:
                result[camel_key] = value
        return result

    async def _execute_step(self, state: ContextSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        review: ReviewData = state.get("review", {})
        context: ContextData = state.get("context", {})

        # Extract analysis data for display
        completeness_score: int | float = review.get("completeness_score", 0)

        # Convert gaps from dict (backend format) to array (frontend Gap[] format)
        gaps_raw = review.get("gaps", {})
        if isinstance(gaps_raw, dict):
            gaps = [
                {
                    "id": gap_value.get("id", gap_key),
                    "category": gap_value.get("category", gap_value.get("type", "general")),
                    "title": gap_value.get("title") or gap_value.get("question", "") or gap_key,
                    "description": gap_value.get("description") or gap_value.get("question", "") or gap_key,
                    "severity": gap_value.get("severity", "medium"),
                }
                for gap_key, gap_value in gaps_raw.items()
                if isinstance(gap_value, dict)
            ]
            logger.info(
                "FeedbackReviewNode: Converted %d gaps from dict to array",
                len(gaps),
            )
        elif isinstance(gaps_raw, list):
            gaps = gaps_raw
            logger.info("FeedbackReviewNode: Gaps already in list format (%d items)", len(gaps))
        else:
            gaps = []
            logger.warning("FeedbackReviewNode: Unexpected gaps type: %s", type(gaps_raw).__name__)

        clarification_questions = review.get("clarification_questions", [])
        raw_actions = review.get("suggested_actions", [])
        suggested_actions: list[dict[str, Any]] = [a if isinstance(a, dict) else {"action": a} for a in raw_actions]

        # Get architectural analysis from deep analysis
        deep_analysis = context.get("deep_analysis_full", {})
        architecture_implications = deep_analysis.get("architecture_implications", {})
        risk_areas = deep_analysis.get("risk_areas", [])
        dependencies = deep_analysis.get("dependencies", {})

        # Normalize architecture_analysis keys from snake_case to camelCase
        architecture_analysis: dict[str, Any] = self._normalize_keys(
            {
                "implications": architecture_implications,
                "risk_areas": risk_areas,
                "dependencies": dependencies,
            }
        )
        impl_keys = (
            list(architecture_analysis.get("implications", {}).keys())
            if architecture_analysis.get("implications")
            else []
        )
        logger.info(
            "FeedbackReviewNode: architecture_analysis keys=%s",
            impl_keys,
        )

        # Build context items summary for frontend display.
        # Prefer reference_urls_meta (artifact-backed) over raw URL strings.
        # The CollectContextNode form stores keys under form-field IDs
        # (reference_urls, primary_document, supporting_docs), while
        # ContextData canonical names differ (extracted_urls,
        # primary_document_id, supporting_doc_ids).  Check both to
        # handle either naming convention.
        context_items: dict[str, Any] = {}

        # URLs with artifact metadata (preferred)
        url_meta = context.get("reference_urls_meta")
        if url_meta:
            context_items["extracted_urls"] = url_meta
        else:
            # Fallback: raw URL strings (no artifact storage)
            extracted_urls = context.get("extracted_urls") or context.get("reference_urls") or []
            if isinstance(extracted_urls, str):
                extracted_urls = [u.strip() for u in extracted_urls.split(",") if u.strip()]
            if extracted_urls:
                context_items["extracted_urls"] = [{"url": u} for u in extracted_urls]
        rounds: list[ContextRound] = context.get("rounds", [])
        if rounds:
            context_items["rounds"] = rounds
        primary_doc_id = context.get("primary_document_id") or context.get("primary_document") or ""
        if primary_doc_id:
            context_items["primary_document_id"] = primary_doc_id
        # Merge reference URL doc IDs with user-uploaded supporting doc IDs.
        # Both keys can be present; the old `or` short-circuit dropped uploads
        # when reference URLs also existed.
        supporting_ids: list[str] = list(context.get("supporting_doc_ids") or [])
        form_supporting = context.get("supporting_docs") or []
        if isinstance(form_supporting, str):
            form_supporting = [s.strip() for s in form_supporting.split(",") if s.strip()]
        for doc_id in form_supporting:
            if doc_id and doc_id not in supporting_ids:
                supporting_ids.append(doc_id)
        if supporting_ids:
            context_items["supporting_doc_ids"] = supporting_ids
        user_explanation = context.get("user_explanation", "")
        if user_explanation:
            context_items["user_explanation"] = user_explanation

        # ── DIAGNOSTIC: log final context_items ──
        logger.info(
            "FeedbackReviewNode: context_items keys=%s  "
            "supporting_doc_ids=%r  primary_document_id=%r  "
            "extracted_urls count=%d  user_explanation=%s",
            list(context_items.keys()),
            context_items.get("supporting_doc_ids"),
            context_items.get("primary_document_id"),
            len(context_items.get("extracted_urls", [])),
            "yes" if context_items.get("user_explanation") else "no",
        )

        # Persist context_items to database for cross-phase access
        try:
            from graph_kb_api.database.base import get_db_session_ctx
            from graph_kb_api.database.plan_repositories import PlanSessionRepository

            session_id = state.get("session_id")
            if session_id and context_items:
                async with get_db_session_ctx() as db_session:
                    repo = PlanSessionRepository(db_session)
                    await repo.update(session_id, context_items=context_items)
        except Exception as e:
            logger.warning("Failed to persist context_items to DB: %s", e)

        # Build interrupt payload for analysis_review type
        interrupt_payload: AnalysisReviewInterruptPayload = {
            "phase": "context",
            "step": "feedback_review",
            "type": "analysis_review",
            "completeness_score": completeness_score,
            "gaps": gaps,
            "clarification_questions": clarification_questions,
            "suggested_actions": suggested_actions,
            "architecture_analysis": architecture_analysis,
            "context_items": context_items,
            "artifacts": self._serialize_artifacts(state["artifacts"]),
            "message": "Review the AI analysis and provide any clarifications before proceeding.",
        }

        # HITL interrupt - wait for user response
        user_response = interrupt(interrupt_payload)

        # Process user response
        answers = user_response.get("answers", {}) if user_response else {}
        additional_context = user_response.get("additional_context", "") if user_response else ""
        architecture_feedback = user_response.get("architecture_feedback", {}) if user_response else {}

        # Build output with user clarifications merged into context
        context_update: Dict[str, Any] = {
            "user_clarifications": answers,
            "additional_context_from_review": additional_context,
        }

        # Merge per-item architecture feedback into context for downstream nodes
        if architecture_feedback:
            context_update["architecture_feedback"] = architecture_feedback
            logger.info(
                "FeedbackReviewNode: received architecture_feedback for %d sections",
                len(architecture_feedback),
            )

        # Also add answered questions to review state for downstream reference
        review_update: Dict[str, Any] = {}
        if answers:
            review_update["answered_questions"] = [{"question_id": qid, "answer": ans} for qid, ans in answers.items()]

        output: Dict[str, Any] = {
            "completed_phases": {"context": True},
        }
        if context_update:
            output["context"] = context_update
        if review_update:
            output["review"] = review_update

        # Emit phase.complete so frontend can mark context phase done
        try:
            configurable: ThreadConfigurable = cast(ThreadConfigurable, config.get("configurable", {}))
            started_at = state.get("budget", {}).get("started_at", "")
            duration_s = (datetime.now(UTC) - datetime.fromisoformat(started_at)).total_seconds() if started_at else 0.0
            await emit_phase_complete(
                session_id=state.get("session_id", ""),
                phase="context",
                result_summary="Context gathering complete",
                duration_s=duration_s,
                client_id=configurable.get("client_id"),
            )
        except Exception:
            pass  # fire-and-forget

        return NodeExecutionResult.success(output=output)
