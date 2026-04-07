"""
ContextReviewAgent - LLM-powered semantic analysis of user specifications.

Analyzes collected context for:
- Completeness and depth
- Ambiguities and contradictions
- Missing requirements
- Documentation gaps
- Suggested clarification questions
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Optional, cast

from langchain_core.messages import AIMessage

from graph_kb_api.core.llm import LLMService
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState
from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt, sanitize_context_for_prompt
from graph_kb_api.websocket.events import PhaseId, emit_phase_progress

logger = logging.getLogger(__name__)


# ── Data Classes ─────────────────────────────────────────────────────────


@dataclass
class DocumentComment:
    """Inline comment on a document or field."""

    target_id: str  # Field or document ID
    target_type: str  # "field" | "document" | "section"
    comment: str
    severity: str  # "info" | "warning" | "error"
    suggestion: Optional[str] = None


@dataclass
class KnowledgeGap:
    """Identified gap in the specification."""

    id: str
    category: str  # "scope" | "technical" | "constraint" | "stakeholder"
    title: str
    description: str
    impact: str  # "high" | "medium" | "low"
    questions: List[str] = dc_field(default_factory=list)
    suggested_answers: List[str] = dc_field(default_factory=list)


@dataclass
class AnalysisResult:
    """Complete analysis result from ContextReviewAgent."""

    completeness_score: float  # 0.0 - 1.0
    document_comments: List[DocumentComment] = dc_field(default_factory=list)
    gaps: List[KnowledgeGap] = dc_field(default_factory=list)
    suggested_actions: List[str] = dc_field(default_factory=list)
    summary: str = ""
    confidence_score: float = 0.5


# ── System Prompt (Metis persona) ──────────────────────────────────────────

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("context_review")


# ── Agent Class ─────────────────────────────────────────────────────────


class ContextReviewAgent(BaseAgent):
    """LLM-powered agent for semantic review of user specifications.

    Extends the rule-based ReviewerCriticAgent with:
    - Semantic understanding of requirements
    - Cross-document consistency checks
    - Intelligent gap detection
    - Context-aware question generation
    - Optional tool usage for codebase/web context
    """

    def __init__(self, tools: Optional[List[Any]] = None, client_id: str | None = None) -> None:
        self._tools = tools or []
        self.client_id: str | None = client_id

    @property
    def capability(self) -> AgentCapability:
        return AgentCapability(
            agent_type="context_review",
            supported_tasks=[
                "analyze_context",
                "detect_gaps",
                "clarification_questions",
                "document_review",
            ],
            required_tools=[],
            optional_tools=["websearch", "search_code", "get_file_content"],
            description=(
                "LLM-powered semantic analysis of user specifications. "
                "Identifies gaps, ambiguities, and generates clarification questions."
            ),
            system_prompt=_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute semantic analysis of context.

        Args:
            task: Contains 'context' with all collected context data
            state: Current wizard state (includes session_id for progress)
            app_context: Application context with LLM and tools

        Returns:
            Dict with analysis_result, completeness_score, gaps_detected,
            document_comments, suggested_actions
        """
        context = task.get("context", {})
        session_id = state.get("session_id")

        if not workflow_context:
            raise RuntimeError("ContextReviewAgent requires a workflow_context but none was provided.")

        try:
            # Step 1: Basic validation (fast, rule-based)
            await self._emit_progress(session_id, "validation", "Running basic validation...", 0.1)
            basic_comments: list[DocumentComment] = self._basic_validation(context)

            # Step 2: Gather codebase context (if available)
            await self._emit_progress(session_id, "context", "Gathering additional context...", 0.2)
            codebase_context: dict[str, Any] = await self._get_codebase_context(context, workflow_context)

            # Step 3: Web research (if tools available)
            await self._emit_progress(session_id, "research", "Researching best practices...", 0.3)
            web_context: dict[str, Any] = await self._web_research(context, workflow_context)

            # Step 4: LLM semantic analysis
            await self._emit_progress(session_id, "analysis", "Analyzing specification semantics...", 0.5)
            llm_result: AnalysisResult = await self._llm_analysis(
                context, codebase_context, web_context, workflow_context
            )

            # Step 5: Merge results
            await self._emit_progress(session_id, "synthesis", "Synthesizing analysis results...", 0.8)
            result: AnalysisResult = self._merge_results(basic_comments, llm_result)

            # Step 6: Complete
            await self._emit_progress(session_id, "complete", "Analysis complete", 1.0)

            return AgentResult(
                agent_type="context_review",
                output=json.dumps(self._serialize_result(result)),
                confidence_score=result.confidence_score,
                confidence_rationale=f"Completeness: {result.completeness_score:.0%}, Gaps: {len(result.gaps)}",
            )

        except Exception as e:
            logger.error(f"ContextReviewAgent failed: {e}", exc_info=True)
            return AgentResult(
                agent_type="context_review",
                error=str(e),
            )

    async def _emit_progress(self, session_id: Optional[str], step: str, message: str, progress: float) -> None:
        """Emit progress event to frontend."""
        if not session_id:
            return

        try:
            await emit_phase_progress(
                session_id=session_id,
                phase=PhaseId.REVIEW,
                step=step,
                message=message,
                progress_pct=progress,
                client_id=self.client_id,
            )
        except Exception as e:
            logger.warning(f"Failed to emit progress: {e}")

    def _basic_validation(self, context: Dict[str, Any]) -> List[DocumentComment]:
        """Fast rule-based validation checks."""
        comments: List[DocumentComment] = []

        # Check required fields
        required = {
            "spec_name": "Feature name",
            "spec_description": "Feature description",
            "user_explanation": "User explanation",
        }
        for field, label in required.items():
            value = context.get(field, "")
            if not value or (isinstance(value, str) and not value.strip()):
                comments.append(
                    DocumentComment(
                        target_id=field,
                        target_type="field",
                        comment=f"{label} is required but empty",
                        severity="error",
                        suggestion=f"Provide a {label.lower()}",
                    )
                )

        # Check for short descriptions
        description = context.get("spec_description", "")
        if isinstance(description, str) and 0 < len(description.strip()) < 50:
            comments.append(
                DocumentComment(
                    target_id="spec_description",
                    target_type="field",
                    comment="Description is too brief for meaningful analysis",
                    severity="warning",
                    suggestion="Expand the description with more details about the feature's purpose and scope",
                )
            )

        # Check for vague terms
        explanation = context.get("user_explanation", "")
        vague_terms = ["fast", "scalable", "user-friendly", "intuitive", "robust"]
        if isinstance(explanation, str):
            found_vague = [t for t in vague_terms if t.lower() in explanation.lower()]
            if found_vague:
                comments.append(
                    DocumentComment(
                        target_id="user_explanation",
                        target_type="field",
                        comment=f"Contains vague terms: {', '.join(found_vague)}",
                        severity="info",
                        suggestion="Replace vague terms with specific, measurable criteria",
                    )
                )

        return comments

    async def _get_codebase_context(self, context: Dict[str, Any], workflow_context: WorkflowContext) -> Dict[str, Any]:
        """Gather context from codebase using available tools."""
        result: Dict[str, Any] = {"related_features": [], "relevant_modules": []}

        repo_id = context.get("target_repo_id")
        if not repo_id:
            return result

        graph_store = getattr(workflow_context, "graph_store", None)
        if not graph_store:
            return result

        # Try to find related features/implementations
        try:
            spec_name = context.get("spec_name", "")
            if spec_name:
                # Use graph_store for semantic search if available
                search_method = getattr(graph_store, "search", None) or getattr(graph_store, "semantic_search", None)
                if search_method and callable(search_method):
                    import asyncio

                    if asyncio.iscoroutinefunction(search_method):
                        related = await search_method(spec_name, limit=5)
                    else:
                        related = search_method(spec_name, limit=5)
                    if related:
                        result["related_features"] = related[:5]
        except Exception as e:
            logger.debug(f"Codebase context search failed: {e}")

        return result

    async def _web_research(self, context: Dict[str, Any], workflow_context: WorkflowContext) -> Dict[str, Any]:
        """Research best practices using web search."""
        result: Dict[str, Any] = {"best_practices": [], "similar_features": []}

        # Check if websearch tool is available
        try:
            from graph_kb_api.flows.v3.tools.websearch import websearch

            spec_name = context.get("spec_name", "")
            if spec_name:
                search_query = f"best practices for {spec_name} feature implementation"
                web_results = await websearch.ainvoke(cast(Any, {"query": search_query, "max_results": 3}))
                if web_results:
                    result["best_practices"] = web_results[:3]
        except Exception as e:
            logger.debug(f"Web research failed: {e}")

        return result

    async def _llm_analysis(
        self,
        context: Dict[str, Any],
        codebase_context: Dict[str, Any],
        web_context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> AnalysisResult:
        """Use LLM for semantic analysis."""
        if not workflow_context.llm:
            raise RuntimeError(
                "ContextReviewAgent requires an LLM but none was provided. "
                "Ensure PlanEngine is initialized with llm=workflow_context.llm"
            )
        llm_raw: LLMService = workflow_context.llm

        # Build tools from workflow context for tool-augmented analysis
        app_context = workflow_context.app_context
        if app_context:
            from graph_kb_api.flows.v3.tools import get_all_tools

            retrieval_config = app_context.get_retrieval_settings()
            tools = get_all_tools(retrieval_config)
        else:
            tools = []

        prompt = self._build_analysis_prompt(context, codebase_context, web_context)

        try:
            # Split prompt into system instructions and user content at first ## heading
            heading_marker = "\n## "
            if heading_marker in prompt:
                system_content = prompt[: prompt.index(heading_marker)].strip()
                user_content = prompt[prompt.index(heading_marker) :]
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ]
            else:
                messages = [{"role": "user", "content": prompt}]
            llm_with_tools = llm_raw.bind_tools(tools) if tools else llm_raw
            response: AIMessage = await llm_with_tools.ainvoke(messages)
            # Handle multi-modal content (str | list[str | dict])
            raw_content = response.content
            content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
            return self._parse_llm_response(content, context)
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
            raise RuntimeError(f"ContextReviewAgent LLM call failed: {e}") from e

    def _build_analysis_prompt(
        self,
        context: Dict[str, Any],
        codebase_context: Dict[str, Any],
        web_context: Dict[str, Any],
    ) -> str:
        """Build the analysis prompt for the LLM."""
        context_json: str = json.dumps(sanitize_context_for_prompt(context), indent=2, default=str)

        extra_context = []
        if codebase_context.get("related_features"):
            extra_context.append(
                f"Related features in codebase: {json.dumps(codebase_context['related_features'][:3], default=str)}"
            )
        if web_context.get("best_practices"):
            bp = web_context["best_practices"][:3]
            # Avoid double-serializing if best_practices items are already strings
            if isinstance(bp, list) and bp and isinstance(bp[0], str):
                extra_context.append(f"Best practices found: {json.dumps(bp)}")
            elif isinstance(bp, str):
                extra_context.append(f"Best practices found: {bp}")
            else:
                extra_context.append(f"Best practices found: {json.dumps(bp, default=str)}")

        extra_context_str = "\n".join(extra_context) if extra_context else "No additional context available."

        prompt = f"""{_SYSTEM_PROMPT}

## Specification Context
```json
{context_json}
```

## Additional Context
{extra_context_str}

Analyze this specification and return your findings as JSON."""
        return append_document_context_to_prompt(prompt, context)

    def _parse_llm_response(self, content: str, context: Dict[str, Any]) -> AnalysisResult:
        """Parse LLM response into AnalysisResult."""
        try:
            # Try to extract JSON from the response
            parsed = self._extract_json(content)

            completeness_score = float(parsed.get("completeness_score", 0.5))
            completeness_score = max(0.0, min(1.0, completeness_score))

            # Parse document comments
            comments: List[DocumentComment] = []
            for c in parsed.get("document_comments", []):
                if isinstance(c, dict):
                    comments.append(
                        DocumentComment(
                            target_id=str(c.get("target_id", "unknown")),
                            target_type=str(c.get("target_type", "field")),
                            comment=str(c.get("comment", "")),
                            severity=str(c.get("severity", "info")),
                            suggestion=c.get("suggestion"),
                        )
                    )

            # Parse gaps
            gaps: List[KnowledgeGap] = []
            for g in parsed.get("gaps", []):
                if isinstance(g, dict):
                    gaps.append(
                        KnowledgeGap(
                            id=str(g.get("id", f"gap_{len(gaps)}")),
                            category=str(g.get("category", "scope")),
                            title=str(g.get("title", "")),
                            description=str(g.get("description", "")),
                            impact=str(g.get("impact", "medium")),
                            questions=list(g.get("questions", [])),
                            suggested_answers=list(g.get("suggested_answers", [])),
                        )
                    )

            return AnalysisResult(
                completeness_score=completeness_score,
                document_comments=comments,
                gaps=gaps,
                suggested_actions=list(parsed.get("suggested_actions", [])),
                summary=str(parsed.get("summary", "Analysis complete")),
                confidence_score=0.8,
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise RuntimeError(f"ContextReviewAgent failed to parse LLM response: {e}") from e

    def _extract_json(self, content: str) -> Dict[str, Any]:
        """Extract JSON from LLM response, handling markdown code blocks."""
        if not content:
            return {}

        # Strip markdown code fences
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        # Try direct parse
        try:
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Try to find a JSON object in the text
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return {}

    def _merge_results(
        self,
        basic_comments: List[DocumentComment],
        llm_result: AnalysisResult,
    ) -> AnalysisResult:
        """Merge basic validation with LLM results."""
        # Combine comments, avoiding duplicates
        existing_targets = {c.target_id for c in llm_result.document_comments}
        merged_comments = list(llm_result.document_comments)

        for c in basic_comments:
            if c.target_id not in existing_targets:
                merged_comments.append(c)

        # Adjust completeness score based on basic validation errors
        error_count = sum(1 for c in merged_comments if c.severity == "error")
        warning_count = sum(1 for c in merged_comments if c.severity == "warning")

        adjusted_score = llm_result.completeness_score
        adjusted_score -= error_count * 0.15
        adjusted_score -= warning_count * 0.05
        adjusted_score = max(0.0, min(1.0, adjusted_score))

        return AnalysisResult(
            completeness_score=adjusted_score,
            document_comments=merged_comments,
            gaps=llm_result.gaps,
            suggested_actions=llm_result.suggested_actions,
            summary=llm_result.summary,
            confidence_score=llm_result.confidence_score,
        )

    def _fallback_result(self, context: Dict[str, Any]) -> AnalysisResult:
        """Generate fallback result when LLM is unavailable."""
        comments = self._basic_validation(context)

        # Basic gap detection
        gaps: List[KnowledgeGap] = []

        if not (
            isinstance(context.get("constraints"), dict) and context["constraints"].get("tech", {}).get("required")
        ):
            gaps.append(
                KnowledgeGap(
                    id="gap_tech_stack",
                    category="technical",
                    title="Technology Stack Undefined",
                    description="No technology stack requirements specified",
                    impact="high",
                    questions=["What technologies should be used for this feature?"],
                    suggested_answers=[
                        "Use existing stack",
                        "New framework: ___",
                        "Open to suggestions",
                    ],
                )
            )

        if not context.get("stakeholders"):
            gaps.append(
                KnowledgeGap(
                    id="gap_stakeholders",
                    category="stakeholder",
                    title="No Stakeholders Identified",
                    description="No stakeholders have been added to this specification",
                    impact="medium",
                    questions=["Who are the key stakeholders for this feature?"],
                    suggested_answers=[
                        "Product owner",
                        "Engineering team",
                        "End users",
                    ],
                )
            )

        # Calculate basic completeness
        has_name = bool(context.get("spec_name", "").strip())
        has_desc = bool(context.get("spec_description", "").strip())
        has_explanation = bool(context.get("user_explanation", "").strip())
        base_score = (has_name + has_desc + has_explanation) / 3.0

        return AnalysisResult(
            completeness_score=base_score,
            document_comments=comments,
            gaps=gaps,
            suggested_actions=[
                "Provide more details",
                "Answer clarification questions",
            ],
            summary="Basic analysis completed (LLM unavailable)",
            confidence_score=0.5,
        )

    # Serialization helpers
    def _serialize_result(self, result: AnalysisResult) -> Dict[str, Any]:
        return {
            "completeness_score": result.completeness_score,
            "document_comments": [self._serialize_comment(c) for c in result.document_comments],
            "gaps": [self._serialize_gap(g) for g in result.gaps],
            "suggested_actions": result.suggested_actions,
            "summary": result.summary,
            "confidence_score": result.confidence_score,
        }

    def _serialize_comment(self, comment: DocumentComment) -> Dict[str, Any]:
        return {
            "target_id": comment.target_id,
            "target_type": comment.target_type,
            "comment": comment.comment,
            "severity": comment.severity,
            "suggestion": comment.suggestion,
        }

    def _serialize_gap(self, gap: KnowledgeGap) -> Dict[str, Any]:
        return {
            "id": gap.id,
            "category": gap.category,
            "title": gap.title,
            "description": gap.description,
            "impact": gap.impact,
            "questions": gap.questions,
            "suggested_answers": gap.suggested_answers,
        }


# ── Register with AgentRegistry ─────────────────────────────────────────
from graph_kb_api.flows.v3.agents.registry import AgentRegistry  # noqa: E402

AgentRegistry.register(ContextReviewAgent)
