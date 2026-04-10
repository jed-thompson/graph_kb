"""Research subgraph nodes for the /plan command.

FormulateQueriesNode, DispatchResearchNode, AggregateNode, GapCheckNode, ConfidenceGateNode, ResearchApprovalNode."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any, Dict, cast

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.services.artifact_service import ArtifactService
    from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.core.llm import LLMService
from graph_kb_api.database.base import get_db_session_ctx
from graph_kb_api.database.document_repositories import (
    DocumentLinkRepository,
    DocumentRepository,
)
from graph_kb_api.flows.v3.agents import AgentResult
from graph_kb_api.flows.v3.agents.gap_analysis_agent import GapAnalysisAgent
from graph_kb_api.flows.v3.agents.personas.prompt_manager import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import AgentTask, ThreadConfigurable
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.nodes.plan.base_approval_node import BaseApprovalNode
from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard
from graph_kb_api.flows.v3.state import ContextData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import (
    RESEARCH_NODE_PROGRESS,
    BudgetState,
    InterruptOption,
    ResearchSubgraphState,
    WorkflowError,
)
from graph_kb_api.flows.v3.state.workflow_state import ResearchSubtask, ReviewData
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator, truncate_to_tokens
from graph_kb_api.flows.v3.utils.json_parsing import parse_json_from_llm
from graph_kb_api.storage.blob_storage import BlobStorage
from graph_kb_api.websocket.plan_events import emit_phase_progress

logger = logging.getLogger(__name__)


class FormulateQueriesNode(SubgraphAwareNode[ResearchSubgraphState]):
    """Formulates search queries for multi-source research.

    Reads context and review to generate structured queries:
    targeting web search, vector search, and KB.
    Returns a targets dict and subtasks list for downstream dispatch.
    """

    def __init__(self) -> None:
        super().__init__(node_name="formulate_queries")
        self.phase = "research"
        self.step_name = "formulate_queries"
        self.step_progress: int | float = RESEARCH_NODE_PROGRESS["formulate_queries"]

    async def _execute_step(self, state: ResearchSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        if not ctx.workflow_context:
            raise RuntimeError("FormulateQueriesNode requires a WorkflowContext but none was provided in config.")
        llm = ctx.require_llm

        budget: BudgetState = ctx.budget

        # Budget check before LLM call
        BudgetGuard.check(budget)

        context: ContextData = state.get("context", {})
        review: ReviewData = state.get("review", {})

        # Build prompt with context
        context_summary = self._summarize_context(context, review)
        base_prompt: str = get_agent_prompt_manager().get_prompt("research_formulate_queries", subdir="nodes")
        prompt = f"{base_prompt}\n\n## Feature Context\n{context_summary}"

        try:
            response = await llm.ainvoke(prompt)
            raw_content = response.content if hasattr(response, "content") else str(response)
            content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content

            # Parse LLM response
            parsed: dict[str, Any] = self._parse_llm_response(content)

            # Decrement budget after LLM call (count response tokens, not prompt)

            new_budget = self._decrement_budget(budget, content)

            return NodeExecutionResult.success(
                output={
                    "research": {
                        "targets": parsed.get("targets", {}),
                        "subtasks": parsed.get("subtasks", []),
                        "queries": parsed.get("queries", []),
                    },
                    "budget": new_budget,
                }
            )
        except Exception as e:
            logger.error(f"FormulateQueriesNode LLM failed: {e}")
            raise RuntimeError(f"FormulateQueriesNode LLM call failed: {e}") from e

    def _summarize_context(self, context: ContextData, review: ReviewData) -> str:
        """Build a concise context summary for the LLM prompt."""
        parts = []
        if context.get("spec_name"):
            parts.append(f"Feature: {context['spec_name']}")
        if context.get("spec_description"):
            parts.append(f"Description: {context['spec_description']}")
        if context.get("user_explanation"):
            parts.append(f"User Explanation: {context['user_explanation']}")
        if context.get("constraints"):
            parts.append(f"Constraints: {context['constraints']}")
        if review.get("gaps"):
            parts.append(f"Identified Gaps: {json.dumps(review['gaps'])}")

        # Append section index so the LLM sees the spec's structure.
        section_index: list[dict[str, Any]] = context.get("document_section_index", [])
        if section_index:
            section_lines = []
            for doc in section_index:
                role_label = doc.get("role", "supporting")
                section_lines.append(f"\n### {doc.get('filename', 'unknown')} ({role_label})")
                for sec in doc.get("sections", []):
                    section_lines.append(f"- {sec.get('heading', 'Untitled')}")
            parts.append("## Section Index\n" + "\n".join(section_lines))

        # Append primary doc content (truncated to 3K tokens).
        doc_contents: list[dict[str, str]] = context.get("uploaded_document_contents", [])
        primary_docs = [d for d in doc_contents if d.get("role") == "primary"]
        if primary_docs:
            parts.append(
                "## Primary Requirements Document\n\n" + truncate_to_tokens(primary_docs[0].get("content", ""), 3_000)
            )

        return "\n".join(parts) if parts else "No context available"

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """Parse LLM response into structured query data."""
        try:
            parsed = parse_json_from_llm(content)
            if isinstance(parsed, dict):
                return parsed
        except ValueError as e:
            logger.debug(f"Failed to parse LLM response: {e}")
        return {"queries": [], "targets": {}, "subtasks": []}


class DispatchResearchNode(SubgraphAwareNode[ResearchSubgraphState]):
    """Dispatches research queries via ResearchAgent.execute().

    Calls the ResearchAgent to execute research across multiple sources
    (codebase, documents, risk analysis, gap detection) and stores
    large results via ArtifactService.
    """

    def __init__(self) -> None:
        super().__init__(node_name="dispatch_research")
        self.phase = "research"
        self.step_name = "dispatch_research"
        self.step_progress = RESEARCH_NODE_PROGRESS["dispatch_research"]

    async def _execute_step(self, state: ResearchSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        from graph_kb_api.flows.v3.agents.research_agent import ResearchAgent

        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})

        subtasks: list[ResearchSubtask] = research.get("subtasks", [])

        if not subtasks:
            logger.warning(
                "[DispatchResearchNode] No subtasks found in research state — "
                "FormulateQueriesNode may have returned empty/invalid results. "
                f"research keys={list(research.keys()) if research else 'empty'}"
            )
            return NodeExecutionResult.success(
                output={
                    "research": {
                        **research,
                        "web_results": [],
                        "vector_results": [],
                        "graph_results": [],
                    },
                }
            )

        BudgetGuard.check(budget)

        # Build the app_context adapter
        if not ctx.workflow_context:
            raise RuntimeError("DispatchResearchNode requires workflow_context")

        # Build the AgentTask the ResearchAgent expects
        agent_task: AgentTask = {
            "description": "Multi-source research dispatch",
            "task_id": f"research_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
            "context": {
                "target_repo_id": context.get("target_repo_id", ""),
                "supporting_docs": context.get("supporting_docs", []),
                "reference_documents": context.get("reference_documents", []),
                "user_explanation": context.get("user_explanation", ""),
                "constraints": context.get("constraints", {}),
                "spec_name": context.get("spec_name", ""),
                "research_targets": research.get("targets", {}),
                "research_subtasks": subtasks,
                "uploaded_document_contents": context.get("uploaded_document_contents", []),
                "document_section_index": context.get("document_section_index", []),
            },
        }

        web_results: list[Dict[str, Any]] = []
        vector_results: list[Dict[str, Any]] = []
        graph_results: list[Dict[str, Any]] = []
        artifacts_output: Dict[str, Any] = {}
        llm_calls = 0

        await self._emit_progress(
            ctx, "dispatch_research", 0.30,
            f"Dispatching research across {len(subtasks)} subtasks",
        )

        agent = ResearchAgent(client_id=ctx.client_id)
        result: AgentResult = await agent.execute(task=agent_task, state=state, workflow_context=ctx.workflow_context)

        # Extract findings from agent result
        # ResearchAgent.execute() returns {"output": json_string, ...}
        # where "output" contains the serialized ResearchFindings dict.
        findings: Dict[str, Any] = {}
        raw_output = result.get("output")
        if isinstance(raw_output, str):
            try:
                findings = json.loads(raw_output)
            except (json.JSONDecodeError, TypeError):
                logger.warning("[DispatchResearchNode] Failed to parse agent output as JSON")
        elif isinstance(raw_output, dict):
            findings = raw_output

        # Also check for direct research_findings key (alternative format)
        if not findings:
            findings = result.get("research_findings", {})

        logger.info(
            f"[DispatchResearchNode] Agent result keys={list(result.keys())}, "
            f"findings keys={list(findings.keys()) if isinstance(findings, dict) else type(findings).__name__}"
        )

        # Map agent output to research state fields
        # The agent returns structured findings — distribute to result categories.
        # Agent may return narrative strings instead of lists; coerce safely.
        def _ensure_list(val: Any) -> list:
            if isinstance(val, list):
                return val
            if val:
                return [val]
            return []

        similar_features = _ensure_list(findings.get("similar_features"))
        relevant_modules = _ensure_list(findings.get("relevant_modules"))
        related_specs = _ensure_list(findings.get("related_specs"))
        api_contracts = _ensure_list(findings.get("api_contracts"))

        # Graph results = codebase analysis (similar features + modules)
        graph_results = similar_features + relevant_modules

        # Vector results = document search results (specs + contracts)
        vector_results = related_specs + api_contracts

        # Web results = any web-sourced data (risks, business rules)
        web_results = _ensure_list(findings.get("business_rules")) + _ensure_list(findings.get("data_schemas"))

        logger.info(
            f"[DispatchResearchNode] Mapped results: "
            f"graph={len(graph_results)} (similar={len(similar_features)}, modules={len(relevant_modules)}), "
            f"vector={len(vector_results)} (specs={len(related_specs)}, contracts={len(api_contracts)}), "
            f"web={len(web_results)}"
        )

        # When all mapped lists are empty but findings has any content,
        # package findings into graph_results so aggregate has data.
        if not (graph_results or vector_results or web_results) and findings:
            logger.info(
                "[DispatchResearchNode] Structured lists empty but findings present "
                f"(keys={list(findings.keys())[:8]}). "
                "Packaging as graph_results for aggregate."
            )
            graph_results = [{"source": "agent_findings", "data": findings}]

        llm_calls = result.get("llm_calls_used", 1)

        await self._emit_progress(
            ctx, "dispatch_research", 0.50,
            f"Research complete — {len(web_results)} web, "
            f"{len(vector_results)} doc, {len(graph_results)} graph results",
        )

        # Store large results via ArtifactService
        if ctx.artifact_service:
            if web_results:
                ref = await ctx.artifact_service.store(
                    "research",
                    "web_results.json",
                    json.dumps(web_results, indent=2, default=str),
                    f"Web/external results ({len(web_results)} items)",
                )
                artifacts_output["research.web_results"] = ref

            if vector_results:
                ref = await ctx.artifact_service.store(
                    "research",
                    "vector_results.json",
                    json.dumps(vector_results, indent=2, default=str),
                    f"Vector/doc results ({len(vector_results)} items)",
                )
                artifacts_output["research.vector_results"] = ref

            if graph_results:
                ref = await ctx.artifact_service.store(
                    "research",
                    "graph_results.json",
                    json.dumps(graph_results, indent=2, default=str),
                    f"Graph KB results ({len(graph_results)} items)",
                )
                artifacts_output["research.graph_results"] = ref

            # Store full findings
            ref = await ctx.artifact_service.store(
                "research",
                "full_findings.json",
                json.dumps(findings, indent=2, default=str),
                findings.get("summary", "Research findings"),
            )
            artifacts_output["research.full_findings"] = ref

        new_budget = self._decrement_budget(budget, str(result), llm_calls=llm_calls)

        # Track whether structured data was actually retrieved (vs narrative fallback).
        # When False, the research loop should not iterate — more passes won't help.
        # On repeat iterations (research_gap_iterations > 0), graph-only results are
        # not counted as "new" structured data — the graph KB is a static index and
        # re-querying it produces the same results. Only web/vector sources indicate
        # genuinely fresh data. This triggers the stagnation early-exit in
        # _route_after_gap_check after 2 iterations when web=0 AND vector=0.
        # Uploaded documents are always treated as available structured data — the
        # gap_check LLM now receives their full content and can resolve gaps directly.
        iteration_count = research.get("research_gap_iterations", 0)
        has_uploaded_docs = bool(context.get("uploaded_document_contents", []))
        has_structured_data = bool(
            has_uploaded_docs
            or web_results
            or vector_results
            or (
                iteration_count == 0
                and graph_results
                and not any(isinstance(r, dict) and r.get("source") == "agent_findings" for r in graph_results)
            )
        )

        return NodeExecutionResult.success(
            output={
                "research": {
                    **research,
                    "web_results": web_results,
                    "vector_results": vector_results,
                    "graph_results": graph_results,
                    "findings": findings if findings else research.get("findings"),
                    "structured_data_available": has_structured_data,
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
            }
        )


class AggregateNode(SubgraphAwareNode[ResearchSubgraphState]):
    """Aggregates research results from multiple sources.

    Synthesizes web_results, vector_results, and graph_results into
    a unified findings structure. Stores the full aggregation via
    ArtifactService and returns a summary.
    """

    def __init__(self) -> None:
        super().__init__(node_name="aggregate")
        self.phase = "research"
        self.step_name = "aggregate"
        self.step_progress = RESEARCH_NODE_PROGRESS["aggregate"]

    async def _execute_step(self, state: ResearchSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        research: ResearchData = state.get("research", {})

        # LOG: Research data coming in
        logger.info(
            f"[AggregateNode] Research data: web={len(research.get('web_results', []))}, "
            f"vector={len(research.get('vector_results', []))}, "
            f"graph={len(research.get('graph_results', []))}"
        )

        # Budget check before LLM call
        BudgetGuard.check(budget)

        # Collect all research results
        web_results = research.get("web_results", [])
        vector_results = research.get("vector_results", [])
        graph_results = research.get("graph_results", [])

        # Build aggregation
        if not ctx.llm:
            raise RuntimeError("AggregateNode requires an LLM but none was provided in config.")

        # Check for raw findings from dispatch_research (agent may return narrative
        # data instead of structured lists)
        raw_findings: Dict[str, Any] = research.get("findings", {})

        if not (web_results or vector_results or graph_results):
            # If raw findings are substantive, fall through to LLM synthesis
            # instead of passing them through unprocessed
            raw_findings_size = len(json.dumps(raw_findings, default=str)) if raw_findings else 0
            if raw_findings and raw_findings_size > 200:
                logger.info(
                    "[AggregateNode] Structured result lists empty but raw findings "
                    f"substantive ({raw_findings_size} chars, "
                    f"keys={list(raw_findings.keys())[:8]}). "
                    "Falling through to LLM synthesis."
                )
                # Don't return early — continue to the LLM synthesis path below
            elif raw_findings:
                logger.info(
                    "[AggregateNode] Structured result lists empty but raw findings "
                    f"present (keys={list(raw_findings.keys())[:8]}). "
                    "Using raw findings directly."
                )
                aggregated = raw_findings
                # Ensure confidence field exists for downstream nodes
                if "confidence" not in aggregated and "confidence_score" in aggregated:
                    aggregated["confidence"] = aggregated["confidence_score"]
                if "confidence" not in aggregated:
                    aggregated["confidence"] = 0.4
                return NodeExecutionResult.success(
                    output={
                        "research": {
                            **research,
                            "findings": aggregated,
                        },
                        "artifacts": {},
                    }
                )

            logger.warning(
                "[AggregateNode] No research results to aggregate — "
                "dispatch_research returned empty with no raw findings. "
                f"web={len(web_results)}, vector={len(vector_results)}, graph={len(graph_results)}. "
                "Returning empty findings so the workflow can continue."
            )
            empty_findings: Dict[str, Any] = {
                "findings": {
                    "summary": "No research results were collected. Gap analysis will rely on the context phase data.",
                    "key_insights": [],
                    "confidence": 0.2,
                    "sources_used": [],
                },
            }
            return NodeExecutionResult.success(
                output={
                    "research": {
                        **research,
                        "findings": empty_findings["findings"],
                    },
                    "artifacts": {},
                }
            )

        context: ContextData = state.get("context", {})
        prompt = self._build_aggregation_prompt(web_results, vector_results, graph_results, context=context)
        response = await ctx.llm.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
        findings_dict, findings_markdown = self._parse_markdown_findings(content)

        # Store full aggregation via ArtifactService
        artifacts_output: Dict[str, Any] = {}
        if ctx.artifact_service and findings_markdown:
            ref = await ctx.artifact_service.store(
                "research",
                "findings.md",
                findings_markdown,
                findings_dict.get("summary", "Research findings"),
            )
            artifacts_output["research.findings"] = ref

        # Persist research findings as a readable markdown document (Blob+DB+Link)
        session_id: str | None = state.get("session_id")
        if session_id and findings_markdown:
            try:
                storage: BlobStorage = ctx.workflow_context.blob_storage if ctx.workflow_context else BlobStorage.from_env()
                async with get_db_session_ctx() as db_session:
                    doc_repo = DocumentRepository(db_session)
                    assoc_repo = DocumentLinkRepository(db_session)

                    content_bytes: bytes = findings_markdown.encode("utf-8")
                    file_hash: str = hashlib.sha256(content_bytes).hexdigest()
                    doc_id = str(uuid.uuid4())
                    storage_key = f"plan_docs/{session_id}/{doc_id}.md"

                    await storage.backend.store(
                        path=storage_key,
                        content=content_bytes,
                        content_type="text/markdown",
                    )
                    await doc_repo.create(
                        storage_key=storage_key,
                        original_filename="research-findings.md",
                        mime_type="text/markdown",
                        file_size=len(content_bytes),
                        uploaded_by="system",
                        storage_backend="local",
                        document_type="research_findings",
                        file_hash=file_hash,
                        metadata={
                            "phase": "research",
                            "confidence_score": findings_dict.get("confidence", 0),
                        },
                        document_id=doc_id,
                    )
                    await db_session.commit()
                    await assoc_repo.associate(
                        source_type="plan_session",
                        source_id=session_id,
                        document_id=doc_id,
                        role="research",
                        associated_by="system",
                        notes="Aggregated research findings",
                    )
                    research["findings_doc_id"] = doc_id
            except Exception as e:
                logger.warning("Failed to persist research findings as document: %s", e)

        # Decrement budget
        new_budget = self._decrement_budget(budget, findings_markdown)

        return NodeExecutionResult.success(
            output={
                "research": {
                    **research,
                    "findings": findings_dict,
                },
                "artifacts": artifacts_output,
                "budget": new_budget,
                "context": state.get("context", {}),
            }
        )

    @staticmethod
    def _parse_markdown_findings(markdown: str) -> tuple[Dict[str, Any], str]:
        """Parse LLM markdown output into structured findings dict + raw markdown.

        Extracts summary, key_insights, confidence, and sources_used from
        the markdown sections for downstream consumers that need individual fields.
        Returns (findings_dict, raw_markdown).
        """
        findings: Dict[str, Any] = {
            "summary": "",
            "key_insights": [],
            "confidence": 0.5,
            "sources_used": [],
        }

        # Extract summary
        summary_match: re.Match[str] | None = re.search(r"##\s*Summary\s*\n+(.*?)(?=\n##\s|\Z)", markdown, re.DOTALL)
        if summary_match:
            findings["summary"] = summary_match.group(1).strip()

        # Extract key insights (numbered list items)
        insights_section: re.Match[str] | None = re.search(
            r"##\s*Key Insights?\s*\n+(.*?)(?=\n##\s|\Z)", markdown, re.DOTALL
        )
        if insights_section:
            findings["key_insights"] = re.findall(r"^\d+\.\s+(.+)$", insights_section.group(1), re.MULTILINE)

        # Extract confidence percentage from bold marker
        confidence_match: re.Match[str] | None = re.search(r"\*\*Confidence:\s*([\d]+)%?\*\*", markdown)
        if confidence_match:
            findings["confidence"] = int(confidence_match.group(1)) / 100.0

        # Extract sources (bullet list)
        sources_section: re.Match[str] | None = re.search(r"##\s*Sources?\s*\n+(.*?)(?=\n##\s|\Z)", markdown, re.DOTALL)
        if sources_section:
            findings["sources_used"] = re.findall(r"^[-*]\s+(.+)$", sources_section.group(1), re.MULTILINE)

        return findings, markdown

    def _build_aggregation_prompt(
        self,
        web_results: list[Dict[str, Any]],
        vector_results: list[Dict[str, Any]],
        graph_results: list[Dict[str, Any]],
        context: ContextData | None = None,
    ) -> str:
        """Build the aggregation prompt with research results and spec context."""
        prompt: str = get_agent_prompt_manager().get_prompt("research_aggregate", subdir="nodes")
        context_parts = [prompt]

        # Include spec context so the LLM can prioritize findings
        if context:
            spec_name = context.get("spec_name", "")
            user_explanation = context.get("user_explanation", "")
            if spec_name or user_explanation:
                spec_context = "\n## Specification Context\n"
                if spec_name:
                    spec_context += f"**Feature:** {spec_name}\n"
                if user_explanation:
                    spec_context += f"**Description:** {truncate_to_tokens(user_explanation, 500)}\n"
                context_parts.append(spec_context)

        if web_results:
            context_parts.append(
                f"\n## Web Results ({len(web_results)} items)\n{json.dumps(web_results[:20], indent=2)}"
            )
        if vector_results:
            context_parts.append(
                f"\n## Vector Results ({len(vector_results)} items)\n{json.dumps(vector_results[:20], indent=2)}"
            )
        if graph_results:
            context_parts.append(
                f"\n## Graph Results ({len(graph_results)} items)\n{json.dumps(graph_results[:20], indent=2)}"
            )

        return "\n".join(context_parts)


class GapCheckNode(SubgraphAwareNode[ResearchSubgraphState]):
    """
    Checks for gaps in research coverage via GapAnalysisAgent (LLM).

    Uses GapAnalysisAgent for semantic gap detection in research findings.

    Returns gaps list that triggers re-routing to formulate_queries if non-empty.
    """

    def __init__(self) -> None:
        super().__init__(node_name="gap_check")
        self.phase = "research"
        self.step_name = "gap_check"
        self.step_progress: int | float = RESEARCH_NODE_PROGRESS["gap_check"]

    async def _execute_step(self, state: ResearchSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        budget: BudgetState = ctx.budget
        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})

        BudgetGuard.check(budget)

        findings = research.get("findings", {})

        gaps = []

        agent = GapAnalysisAgent()
        if not ctx.workflow_context:
            raise RuntimeError("GapCheckNode requires a workflow_context but none was provided in config.")

        agent_task: AgentTask = {
            "description": "Research gap analysis",
            "task_id": f"gap_check_{ctx.session_id}_{uuid.uuid4().hex[:8]}",
            "specification": {
                "spec_name": context.get("spec_name", ""),
                "user_explanation": context.get("user_explanation", ""),
            },
            "research_findings": findings,
            "context": {
                "research_phase": True,
                "document_section_index": context.get("document_section_index", []),
                "uploaded_document_contents": context.get("uploaded_document_contents", []),
            },
        }

        result: AgentResult = await agent.execute(task=agent_task, state={}, workflow_context=ctx.workflow_context)

        # Convert agent gaps to node format
        for gap in result.get("gaps", []):
            gaps.append(
                {
                    "gap_id": gap.get("id", f"gap_{len(gaps)}"),
                    "section_id": context.get("spec_name", "research"),
                    "gap_type": gap.get("category", "requirements"),
                    "description": gap.get("description", ""),
                    "question": gap.get("question_to_ask", ""),
                    "context": gap.get("title", ""),
                    "source": "llm_semantic",
                    "importance": gap.get("impact", "medium"),
                    "suggested_queries": [gap.get("suggested_resolution", "")]
                    if gap.get("suggested_resolution")
                    else [],
                }
            )

        llm_calls = 1
        tokens_used: int = get_token_estimator().count_tokens(str(result))

        logger.info(f"GapCheckNode: LLM semantic analysis found {len(gaps)} gaps")
        for i, gap in enumerate(gaps):
            logger.info(
                f"GapCheckNode: Gap {i + 1}: id={gap.get('gap_id')}, "
                f"type={gap.get('gap_type')}, question={gap.get('question', '')[:100]}"
            )

        # Build detailed gap summary for progress event
        iteration = research.get("research_gap_iterations", 0) + 1
        if gaps:
            gap_lines = "\n".join(
                "- **{gid}** [{imp}]: {txt}".format(
                    gid=g.get("gap_id", "?"),
                    imp=g.get("importance", "medium"),
                    txt=(lambda t: t[:117].rsplit(" ", 1)[0] + "..." if len(t) > 120 else t)(
                        g.get("question", g.get("description", ""))
                    ),
                )
                for g in gaps[:15]
            )
            gap_message = f"### Gap Analysis (iteration {iteration})\nFound {len(gaps)} gaps:\n\n{gap_lines}"
        else:
            gap_message = f"Gap analysis complete — no gaps found (iteration {iteration})"

        logger.info(
            "GapCheckNode: Emitting progress with %d gaps for iteration %d",
            len(gaps),
            iteration,
        )
        try:
            await emit_phase_progress(
                session_id=ctx.session_id,
                phase="research",
                step="gap_check",
                message=f"Gap analysis iteration {iteration}: {len(gaps)} gaps found",
                progress_pct=0.70,
                client_id=ctx.client_id,
                agent_content=gap_message,
            )
        except Exception as e:
            logger.warning(f"GapCheckNode emit_phase_progress failed: {e}")

        new_budget = self._decrement_budget(budget, str(result))

        return NodeExecutionResult.success(
            output={
                "research": {
                    **research,
                    "gaps": gaps,
                    "research_gap_iterations": research.get("research_gap_iterations", 0) + 1,
                },
                "budget": new_budget,
            }
        )


class ConfidenceGateNode(SubgraphAwareNode[ResearchSubgraphState]):
    """Gates research completion based on confidence threshold.

    Uses LLM-based evaluation to assess whether research findings are
    sufficient for the specification.
    """

    CONFIDENCE_THRESHOLD = 0.7
    MAX_ITERATIONS = 3

    def __init__(self) -> None:
        super().__init__(node_name="confidence_gate")
        self.phase = "research"
        self.step_name = "confidence_gate"
        self.step_progress = RESEARCH_NODE_PROGRESS["confidence_gate"]

    async def _execute_step(self, state: ResearchSubgraphState, config: RunnableConfig) -> NodeExecutionResult:
        ctx = self._unpack(state, config)
        llm = ctx.require_llm
        budget: BudgetState = ctx.budget

        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})
        findings_dict = research.get("findings", {})
        iteration_count = research.get("research_gap_iterations", 0)

        gaps = [g for g in findings_dict.get("gaps", []) if isinstance(g, dict)]
        risks = [r for r in findings_dict.get("risks", []) if isinstance(r, dict)]

        BudgetGuard.check(budget)

        confidence, justification = await self._llm_evaluate_confidence(llm, context, findings_dict, gaps, risks)

        logger.info("ConfidenceGateNode: LLM confidence=%.2f", confidence)

        # Check thresholds
        confidence_sufficient: bool = confidence >= self.CONFIDENCE_THRESHOLD
        max_iterations_reached = iteration_count >= self.MAX_ITERATIONS
        can_proceed: bool = confidence_sufficient or max_iterations_reached

        new_budget = self._decrement_budget(budget, justification)

        output: Dict[str, Any] = {
            "research": {
                **research,
                "confidence_score": confidence,
                "confidence_sufficient": confidence_sufficient,
                "confidence_evaluation_method": "llm",
                "research_gap_iterations": iteration_count + 1,
                "can_proceed_to_approval": can_proceed,
            },
            "budget": new_budget,
        }

        if not confidence_sufficient and not max_iterations_reached:
            output["research"]["needs_more_research"] = True
            output["research"]["confidence_gap"] = self.CONFIDENCE_THRESHOLD - confidence

        return NodeExecutionResult.success(output=output)

    @staticmethod
    async def _llm_evaluate_confidence(
        llm: LLMService,
        context: ContextData,
        findings: Dict[str, Any],
        gaps: list[Dict[str, Any]],
        risks: list[Dict[str, Any]],
    ) -> tuple[float, str]:
        """Use LLM to evaluate research confidence.

        Returns:
            Tuple of (confidence_score, justification_text).
        """
        spec_name = context.get("spec_name", "Unknown")
        user_explanation = context.get("user_explanation", "Not provided")
        research_summary = findings.get("summary", "No summary")
        gap_descriptions = [
            f"[{g.get('type', 'unknown').upper()} / importance={g.get('importance', 'medium')}] "
            f"{g.get('question', g.get('description', ''))}"
            for g in gaps if isinstance(g, dict)
        ]
        risk_descriptions = [r.get("description", "") for r in risks if isinstance(r, dict)]

        prompt = get_agent_prompt_manager().render_prompt(
            "research_confidence_gate",
            subdir="nodes",
            spec_name=spec_name,
            user_explanation=user_explanation,
            research_summary=research_summary,
            gap_count=len(gap_descriptions),
            gap_descriptions=json.dumps(gap_descriptions[:10], indent=2) if gap_descriptions else "None",
            risk_count=len(risk_descriptions),
            risk_descriptions=json.dumps(risk_descriptions[:10], indent=2) if risk_descriptions else "None",
        )

        # Append section index for per-section confidence evaluation (M2)
        section_index = context.get("document_section_index", [])
        if section_index:
            section_lines = []
            for doc in section_index:
                role_label = doc.get("role", "supporting")
                section_lines.append(f"\n### {doc.get('filename', 'unknown')} ({role_label})")
                for sec in doc.get("sections", []):
                    section_lines.append(f"- {sec.get('heading', 'Untitled')}")
            prompt += "\n\n## Document Section Index\n"
            prompt += "".join(section_lines)
            prompt += "\n\nEvaluate per-section research coverage using the above index."

        response = await llm.ainvoke(prompt)
        raw_content = response.content if hasattr(response, "content") else str(response)
        response_text: str = str(raw_content) if not isinstance(raw_content, str) else raw_content

        # Parse confidence score from response
        score_match = re.search(r"CONFIDENCE:\s*([\d.]+)", response_text)
        if score_match:
            score = float(score_match.group(1))
            score = max(0.0, min(1.0, score))  # Clamp to [0, 1]
        else:
            score = 0.5  # Default if parsing fails

        justification_match = re.search(r"JUSTIFICATION:\s*(.+)", response_text, re.DOTALL)
        justification = justification_match.group(1).strip() if justification_match else response_text

        return score, justification


class ResearchApprovalNode(BaseApprovalNode[ResearchSubgraphState]):
    """Approval gate for research phase completion.

    Presents research summary to user for approval before proceeding
    to planning phase. Extends BaseApprovalNode with research-specific hooks.

    Requirements: 6.3, 6.5
    """

    phase_data_key = "research"

    def __init__(self) -> None:
        super().__init__(node_name="research_approval")
        self.phase = "research"
        self.step_name = "approval"
        self.step_progress = RESEARCH_NODE_PROGRESS["approval"]

    def _build_summary(self, state: ResearchSubgraphState) -> dict[str, Any]:
        research: ResearchData = state.get("research", {})
        context: ContextData = state.get("context", {})
        findings = research.get("findings", {})

        all_gaps = research.get("gaps", [])
        sources_used: list[str] = findings.get("sources_used", [])
        key_insights: list[str] = findings.get("key_insights", [])
        summary = {
            "spec_name": context.get("spec_name", "Unknown"),
            "confidence_score": research.get("confidence_score", findings.get("confidence", 0.5)),
            "sources_used": sources_used,
            "key_insights": key_insights[:5],
            "gaps_remaining": len(all_gaps),
            "total_gaps_detected": len(all_gaps),
            "all_gaps": [
                {
                    "id": g.get("gap_id", g.get("id", "")),
                    "question": g.get("question", g.get("description", "")),
                    "importance": g.get("importance", g.get("severity", "medium")),
                }
                for g in all_gaps
            ],
            "research_iterations": research.get("research_gap_iterations", 0),
            "evaluation_method": research.get("confidence_evaluation_method", "unknown"),
        }

        logger.info(
            "ResearchApprovalNode: summary built — confidence=%.2f, gaps=%d, sources=%d",
            summary["confidence_score"],
            summary["gaps_remaining"],
            len(sources_used),
        )
        return summary

    def _get_approval_options(self) -> list[InterruptOption]:
        return [
            {"id": "approve", "label": "Approve & Continue"},
            {"id": "request_more", "label": "Request More Research"},
            {"id": "reject", "label": "Reject & Restart"},
        ]

    def _get_approval_message(self, summary: dict[str, Any]) -> str:
        return (
            f"Research complete with {summary['confidence_score']:.0%} confidence. "
            f"Approve to proceed to planning?"
        )

    def _process_approve(self, state: ResearchSubgraphState, feedback: str) -> dict[str, Any]:
        research: ResearchData = state.get("research", {})
        return {
            "research": {
                **research,
                "approved": True,
                "approval_decision": "approve",
                "approval_feedback": feedback,
                "review_feedback": feedback,
            },
        }

    def _process_revise(self, state: ResearchSubgraphState, feedback: str) -> dict[str, Any]:
        research: ResearchData = state.get("research", {})
        return {
            "research": {
                **research,
                "approved": False,
                "approval_decision": "request_more",
                "approval_feedback": feedback,
                "review_feedback": feedback,
                "needs_more_research": True,
            },
        }

    def _process_reject(self, state: ResearchSubgraphState, feedback: str) -> dict[str, Any]:
        research: ResearchData = state.get("research", {})
        return {
            "research": {
                **research,
                "approved": False,
                "approval_decision": "reject",
                "approval_feedback": feedback,
                "review_feedback": feedback,
                "rejected": True,
            },
            "workflow_status": "rejected",
            "paused_phase": "research",
            "error": WorkflowError(
                message="Research was rejected by user.",
                code="REJECTED",
                phase="research",
            ),
        }
