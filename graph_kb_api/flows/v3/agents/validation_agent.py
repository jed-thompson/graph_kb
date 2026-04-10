"""
ValidationAgent - LLM-powered document validation.

Validates assembled documents for:
- Completeness and coverage
- Quality and professionalism
- Requirement traceability
- Consistency and coherence
- Section quality assessment
- Improvement recommendations

Used by ValidateNode in the plan workflow assembly phase.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Dict, List, Mapping, Optional

from langchain_core.messages import AIMessage

from graph_kb_api.core.llm import LLMService, LLMQuotaExhaustedError
from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import AgentResult, AgentTask
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.utils.token_estimation import truncate_to_tokens

logger = logging.getLogger(__name__)


# ── Data Classes ─────────────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    """Represents a validation issue found in the document."""

    id: str
    category: str  # "completeness" | "quality" | "consistency" | "traceability"
    severity: str  # "error" | "warning" | "info"
    title: str
    description: str
    location: Optional[str] = None  # Section or field affected
    suggestion: Optional[str] = None


@dataclass
class SectionReview:
    """Quality review for a single document section."""

    section_id: str
    section_title: str
    quality_score: float  # 0.0 - 1.0
    is_weak: bool  # True if section is underdeveloped
    issues: List[str]
    strengths: List[str]
    improvement_suggestions: List[str]


@dataclass
class TraceabilityMapping:
    """Maps a requirement to its coverage in the document."""

    requirement_id: str
    requirement_text: str
    covered: bool
    covered_in_sections: List[str]
    coverage_quality: str  # "full" | "partial" | "none"


@dataclass
class ValidationResult:
    """Complete validation result."""

    is_valid: bool
    issues: List[ValidationIssue]
    quality_score: float  # 0.0 - 1.0
    completeness_score: float  # 0.0 - 1.0
    summary: str
    recommendations: List[str]
    section_reviews: List[SectionReview] = dc_field(default_factory=list)
    traceability_matrix: List[TraceabilityMapping] = dc_field(default_factory=list)
    weak_sections: List[str] = dc_field(default_factory=list)


# ── System Prompt (Oracle persona) ────────────────────────────────────────

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("validation")


class ValidationAgent(BaseAgent):
    """LLM-powered agent for validating assembled documents.

    Validates documents for completeness, quality, consistency,
    requirement traceability, and section quality.
    """

    def __init__(self, tools: Optional[List[Any]] = None):
        self._tools = tools or []

    @property
    def capability(self) -> AgentCapability:
        return AgentCapability(
            agent_type="validation",
            supported_tasks=[
                "document_validation",
                "quality_assessment",
                "completeness_check",
                "consistency_validation",
                "requirement_traceability",
                "section_quality_review",
            ],
            required_tools=[],
            optional_tools=["search_code", "get_file_content"],
            description=(
                "LLM-powered document validation. "
                "Checks completeness, quality, consistency, traceability, and section quality."
            ),
            system_prompt=_SYSTEM_PROMPT,
        )

    async def execute(
        self,
        task: AgentTask,
        state: Mapping[str, Any],
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Execute document validation.

        Args:
            task: Contains 'document' and 'requirements'
            state: Current workflow state
            workflow_context: Application context with LLM

        Returns:
            Dict with validation result, scores, section reviews, and traceability
        """
        task_context = task.get("context", {})
        if not isinstance(task_context, Mapping):
            task_context = {}

        # ValidateNode passes agent inputs via task["context"], while some
        # older callers use top-level task["document"]/["requirements"].
        # Support both shapes so validation receives the assembled document.
        document = task["document"] if "document" in task else task_context.get("document", {})
        requirements = (
            task["requirements"] if "requirements" in task else task_context.get("requirements", [])
        )

        try:
            # Run validation
            result: ValidationResult = await self._validate_document(document, requirements, workflow_context, state)
            serialized: dict[str, Any] = self._serialize_result(result)

            return AgentResult(
                output=json.dumps(serialized),
                agent_type="validation",
                confidence_score=result.quality_score,
                confidence_rationale=result.summary,
                # Include structured data for downstream consumers
                **serialized,  # type: ignore[arg-type]
            )

        except Exception as e:
            # Re-raise quota exhaustion so the node-level handler can emit
            # a proper error to the UI instead of silently degrading
            if isinstance(e, LLMQuotaExhaustedError) or (
                isinstance(e.__cause__, LLMQuotaExhaustedError) if e.__cause__ else False
            ):
                raise

            logger.error(f"ValidationAgent failed: {e}", exc_info=True)
            error_data = {
                "is_valid": False,
                "quality_score": 0.0,
                "completeness_score": 0.0,
                "issues": [],
                "recommendations": ["Fix validation error"],
                "summary": f"Validation failed: {e}",
                "section_reviews": [],
                "traceability_matrix": [],
                "weak_sections": [],
            }
            return AgentResult(
                output=json.dumps(error_data),
                agent_type="validation",
                error=str(e),
                confidence_score=0.0,
                confidence_rationale=f"Validation failed: {e}",
            )

    async def _validate_document(
        self,
        document: Dict[str, Any],
        requirements: List[Any],
        workflow_context: WorkflowContext | None,
        state: Mapping[str, Any],
    ) -> ValidationResult:
        """Validate document using LLM."""
        if workflow_context is None:
            raise RuntimeError("ValidationAgent requires a WorkflowContext")
        llm: LLMService = workflow_context.require_llm

        all_tools = state.get("available_tools", [])
        assigned_tools: list[Any] = [
            t for t in all_tools if hasattr(t, "name") and t.name in self.capability.optional_tools
        ]

        prompt = self._build_validation_prompt(document, requirements)

        try:
            response: AIMessage = await llm.bind_tools(assigned_tools).ainvoke([{"role": "user", "content": prompt}])
            # Handle multi-modal content (str | list[str | dict])
            raw_content = response.content
            content: str = str(raw_content) if not isinstance(raw_content, str) else raw_content
            return self._parse_llm_response(content, document, requirements)
        except Exception as e:
            # Let quota errors propagate without wrapping
            if isinstance(e, LLMQuotaExhaustedError):
                raise
            logger.error(f"LLM validation failed: {e}")
            raise RuntimeError(f"ValidationAgent LLM call failed: {e}") from e

    def _build_validation_prompt(
        self,
        document: Dict[str, Any],
        requirements: List[Any],
    ) -> str:
        """Build the validation prompt with token-aware truncation."""
        # Token limits tuned for modern models (GPT-5, Claude Opus/Sonnet, GLM-5)
        # These models have 128k-200k context windows
        doc_json = truncate_to_tokens(
            json.dumps(document, indent=2, default=str),
            max_tokens=16000,  # ~12k words, covers full spec documents
        )
        req_json = truncate_to_tokens(
            json.dumps(requirements, indent=2, default=str),
            max_tokens=4000,  # ~3k words, full requirements list
        )

        return (
            f"{_SYSTEM_PROMPT}\n\n"
            f"## Document to Validate\n```json\n{doc_json}\n```\n\n"
            f"## Requirements to Check Against\n```json\n{req_json}\n```\n\n"
            "Validate this document thoroughly. For each section, assess quality. "
            "For each requirement, verify traceability. Return your findings as JSON."
        )

    def _parse_llm_response(
        self,
        content: str,
        document: Dict[str, Any],
        requirements: List[Any],
    ) -> ValidationResult:
        """Parse LLM response into ValidationResult."""
        try:
            # Try to extract JSON
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```\s*$", "", cleaned)

            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise ValueError("Response is not a JSON object")

            # Parse issues
            issues: List[ValidationIssue] = []
            for i_data in parsed.get("issues", []):
                if isinstance(i_data, dict):
                    issues.append(
                        ValidationIssue(
                            id=str(i_data.get("id", f"issue_{len(issues)}")),
                            category=str(i_data.get("category", "quality")),
                            severity=str(i_data.get("severity", "info")),
                            title=str(i_data.get("title", "")),
                            description=str(i_data.get("description", "")),
                            location=i_data.get("location"),
                            suggestion=i_data.get("suggestion"),
                        )
                    )

            # Parse section reviews
            section_reviews: List[SectionReview] = []
            for s_data in parsed.get("section_reviews", []):
                if isinstance(s_data, dict):
                    section_reviews.append(
                        SectionReview(
                            section_id=str(s_data.get("section_id", "")),
                            section_title=str(s_data.get("section_title", "")),
                            quality_score=float(s_data.get("quality_score", 0.5)),
                            is_weak=bool(s_data.get("is_weak", False)),
                            issues=list(s_data.get("issues", [])),
                            strengths=list(s_data.get("strengths", [])),
                            improvement_suggestions=list(s_data.get("improvement_suggestions", [])),
                        )
                    )

            # Parse traceability matrix
            traceability_matrix: List[TraceabilityMapping] = []
            for t_data in parsed.get("traceability_matrix", []):
                if isinstance(t_data, dict):
                    traceability_matrix.append(
                        TraceabilityMapping(
                            requirement_id=str(t_data.get("requirement_id", "")),
                            requirement_text=str(t_data.get("requirement_text", "")),
                            covered=bool(t_data.get("covered", False)),
                            covered_in_sections=list(t_data.get("covered_in_sections", [])),
                            coverage_quality=str(t_data.get("coverage_quality", "none")),
                        )
                    )

            # Get weak sections
            weak_sections = list(parsed.get("weak_sections", []))

            return ValidationResult(
                is_valid=bool(parsed.get("is_valid", True)),
                issues=issues,
                quality_score=float(parsed.get("quality_score", 0.5)),
                completeness_score=float(parsed.get("completeness_score", 0.5)),
                summary=str(parsed.get("summary", "Validation complete")),
                recommendations=list(parsed.get("recommendations", [])),
                section_reviews=section_reviews,
                traceability_matrix=traceability_matrix,
                weak_sections=weak_sections,
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise RuntimeError(f"ValidationAgent failed to parse LLM response: {e}") from e

    def _serialize_result(self, result: ValidationResult) -> Dict[str, Any]:
        return {
            "is_valid": result.is_valid,
            "issues": [self._serialize_issue(i) for i in result.issues],
            "quality_score": result.quality_score,
            "completeness_score": result.completeness_score,
            "summary": result.summary,
            "recommendations": result.recommendations,
            "section_reviews": [self._serialize_section_review(s) for s in result.section_reviews],
            "traceability_matrix": [self._serialize_traceability(t) for t in result.traceability_matrix],
            "weak_sections": result.weak_sections,
        }

    def _serialize_issue(self, issue: ValidationIssue) -> Dict[str, Any]:
        return {
            "id": issue.id,
            "category": issue.category,
            "severity": issue.severity,
            "title": issue.title,
            "description": issue.description,
            "location": issue.location,
            "suggestion": issue.suggestion,
        }

    def _serialize_section_review(self, review: SectionReview) -> Dict[str, Any]:
        return {
            "section_id": review.section_id,
            "section_title": review.section_title,
            "quality_score": review.quality_score,
            "is_weak": review.is_weak,
            "issues": review.issues,
            "strengths": review.strengths,
            "improvement_suggestions": review.improvement_suggestions,
        }

    def _serialize_traceability(self, mapping: TraceabilityMapping) -> Dict[str, Any]:
        return {
            "requirement_id": mapping.requirement_id,
            "requirement_text": mapping.requirement_text,
            "covered": mapping.covered,
            "covered_in_sections": mapping.covered_in_sections,
            "coverage_quality": mapping.coverage_quality,
        }


# ── Register with AgentRegistry ─────────────────────────────────────

from graph_kb_api.flows.v3.agents.registry import AgentRegistry  # noqa: E402

AgentRegistry.register(ValidationAgent)
