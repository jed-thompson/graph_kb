"""
GapAnalysisAgent - LLM-powered semantic gap detection.

Analyzes specifications and research findings for:
- Semantic gaps in requirements coverage
- Missing context for task execution
- Information that should be clarified

Used by GapCheckNode and GapNode in the plan workflow.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from graph_kb_api.flows.v3.utils.context_utils import append_document_context_to_prompt, sanitize_context_for_prompt

if TYPE_CHECKING:
    from graph_kb_api.flows.v3.state import UnifiedSpecState

from langchain.messages import AIMessage

from graph_kb_api.core.llm import LLMService, LLMQuotaExhaustedError
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

logger = logging.getLogger(__name__)


# ── Data Classes ─────────────────────────────────────────────────────────


@dataclass
class GapIssue:
    """Represents a detected gap in requirements or context."""

    id: str
    category: str  # "requirements" | "context" | "scope" | "technical" | "constraint"
    title: str
    description: str
    impact: str  # "high" | "medium" | "low"
    question_to_ask: Optional[str] = None
    suggested_resolution: Optional[str] = None


@dataclass
class GapAnalysisResult:
    """Complete gap analysis result."""

    gaps: List[GapIssue]
    completeness_score: float  # 0.0 - 1.0
    summary: str
    confidence_score: float = 0.5


# ── System Prompt (Metis persona) ──────────────────────────────────────────

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("gap_analysis")


# ── Agent Class ─────────────────────────────────────────────────────────


class GapAnalysisAgent(BaseAgent):
    """LLM-powered agent for semantic gap detection.

    This agent analyzes specifications and research findings to identify
    semantic gaps that deterministic checks would miss. Used by GapCheckNode
    and GapNode in the plan workflow.

    The agent uses the Metis (analyst.md) persona for pre-planning consultation.
    """

    @property
    def capability(self) -> AgentCapability:
        return AgentCapability(
            agent_type="gap_analysis",
            supported_tasks=[
                "gap_detection",
                "requirements_analysis",
                "semantic_gap_check",
                "context_gap_analysis",
            ],
            required_tools=[],
            optional_tools=["search_code", "get_file_content"],
            description="Identifies semantic gaps in requirements and context using the Metis persona",
            system_prompt=_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute gap analysis.

        Args:
            task: Contains 'specification' and optional 'research_findings'
            state: Current workflow state
            workflow_context: Application context with LLM

        Returns:
            Dict with gaps, completeness_score, summary, confidence_score
        """
        if not workflow_context:
            raise RuntimeError("GapAnalysisAgent requires a workflow_context but none was provided.")

        specification = task.get("specification", {})
        research_findings = task.get("research_findings", {})
        context = task.get("context", {})

        try:
            # Use LLM for semantic gap analysis
            llm_result: GapAnalysisResult = await self._llm_gap_analysis(
                specification, research_findings, context, workflow_context
            )

            return {
                "gaps": [self._serialize_gap(g) for g in llm_result.gaps],
                "completeness_score": llm_result.completeness_score,
                "summary": llm_result.summary,
                "confidence_score": llm_result.confidence_score,
            }

        except Exception as e:
            # Re-raise quota exhaustion so the node-level handler can emit
            # a proper error to the UI instead of silently degrading
            if isinstance(e, LLMQuotaExhaustedError) or (
                isinstance(e.__cause__, LLMQuotaExhaustedError) if e.__cause__ else False
            ):
                raise

            logger.error(f"GapAnalysisAgent failed: {e}", exc_info=True)
            raise RuntimeError(f"GapAnalysisAgent execute failed: {e}") from e

    async def _llm_gap_analysis(
        self,
        specification: Dict[str, Any],
        research_findings: Dict[str, Any],
        context: Dict[str, Any],
        workflow_context: WorkflowContext,
    ) -> GapAnalysisResult:
        """Use LLM for semantic gap analysis."""
        llm: LLMService = workflow_context.require_llm

        prompt: str = self._build_analysis_prompt(specification, research_findings, context)

        try:
            # Split prompt into system instructions and user content at first ## heading
            heading_marker = "\n## "
            if heading_marker in prompt:
                system_content = prompt[: prompt.index(heading_marker)].strip()
                user_content = prompt[prompt.index(heading_marker):]
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                ]
            else:
                messages = [{"role": "user", "content": prompt}]
            response: AIMessage = await llm.ainvoke(messages)
            raw_content = response.content if hasattr(response, "content") else str(response)
            content = str(raw_content) if not isinstance(raw_content, str) else raw_content
            return self._parse_llm_response(content, specification)
        except Exception as e:
            # Let quota errors propagate without wrapping
            if isinstance(e, LLMQuotaExhaustedError):
                raise
            logger.error(f"LLM gap analysis failed: {e}")
            raise RuntimeError(f"GapAnalysisAgent LLM call failed: {e}") from e

    def _build_analysis_prompt(
        self,
        specification: Dict[str, Any],
        research_findings: Dict[str, Any],
        context: Dict[str, Any],
    ) -> str:
        """Build the analysis prompt for the LLM."""
        spec_json: str = json.dumps(specification, indent=2, default=str)
        research_json: str = json.dumps(research_findings, indent=2, default=str)
        context_json: str = json.dumps(sanitize_context_for_prompt(context), indent=2, default=str)

        prompt = f"""{_SYSTEM_PROMPT}

## Specification to Analyze
```json
{spec_json}
```

## Research Findings
```json
{research_json}
```

## Additional Context
```json
{context_json}
```

Analyze this specification and identify gaps. Return your findings as JSON."""
        return append_document_context_to_prompt(prompt, context)

    def _parse_llm_response(self, content: str, specification: Dict[str, Any]) -> GapAnalysisResult:
        """Parse LLM response into GapAnalysisResult."""
        try:
            parsed = self._extract_json(content)

            gaps = []
            for g in parsed.get("gaps", []):
                if isinstance(g, dict):
                    gaps.append(
                        GapIssue(
                            id=str(g.get("id", f"gap_{len(gaps)}")),
                            category=str(g.get("category", "requirements")),
                            title=str(g.get("title", "")),
                            description=str(g.get("description", "")),
                            impact=str(g.get("impact", "medium")),
                            question_to_ask=g.get("question_to_ask"),
                            suggested_resolution=g.get("suggested_resolution"),
                        )
                    )

            return GapAnalysisResult(
                gaps=gaps,
                completeness_score=float(parsed.get("completeness_score", 0.5)),
                summary=str(parsed.get("summary", "Analysis complete")),
                confidence_score=float(parsed.get("confidence_score", 0.5)),
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise RuntimeError(f"GapAnalysisAgent failed to parse LLM response: {e}") from e

    def _extract_json(self, content: str) -> Dict[str, Any]:
        """Extract JSON from LLM response."""
        import re

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

        # Try to find JSON object
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        return {}

    def _create_fallback_result(self, specification: Dict[str, Any], context: Dict[str, Any]) -> GapAnalysisResult:
        """Create fallback result when LLM unavailable."""
        gaps = []

        # Basic gap detection
        if not specification.get("spec_name"):
            gaps.append(
                GapIssue(
                    id="gap_name",
                    category="requirements",
                    title="Missing Feature Name",
                    description="No feature name provided",
                    impact="high",
                    question_to_ask="What is the name of this feature?",
                )
            )

        if not specification.get("spec_description"):
            gaps.append(
                GapIssue(
                    id="gap_description",
                    category="requirements",
                    title="Missing Feature Description",
                    description="No feature description provided",
                    impact="high",
                    question_to_ask="Please describe what this feature does.",
                )
            )

        return GapAnalysisResult(
            gaps=gaps,
            completeness_score=0.3 if gaps else 0.5,
            summary="Basic gap analysis (LLM unavailable)",
            confidence_score=0.3,
        )

    def _serialize_gap(self, gap: GapIssue) -> Dict[str, Any]:
        """Serialize a GapIssue to dict."""
        return {
            "id": gap.id,
            "category": gap.category,
            "title": gap.title,
            "description": gap.description,
            "impact": gap.impact,
            "question_to_ask": gap.question_to_ask,
            "suggested_resolution": gap.suggested_resolution,
        }


# ── Register with AgentRegistry ─────────────────────────────────────

from graph_kb_api.flows.v3.agents.registry import AgentRegistry  # noqa: E402

AgentRegistry.register(GapAnalysisAgent)
