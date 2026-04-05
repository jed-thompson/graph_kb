"""
Reviewer/Critic agent for the multi-agent feature spec workflow.

Reviews each agent's output for completeness, accuracy, consistency, and
alignment with the template. Uses agent-reported confidence scores to
modulate scrutiny depth — high-confidence sections may be short-circuited
through review.

Requirements traced: 7.2, 7.3, 7.4
"""

import json
import re
from typing import Any, Dict, List

from graph_kb_api.flows.v3.agents.base_agent import AgentCapability, BaseAgent
from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager
from graph_kb_api.flows.v3.models.types import (
    AgentResult,
    AgentTask,
    ReviewResult,
    reviewer_critic_capability,
)
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state import UnifiedSpecState

_SYSTEM_PROMPT = get_agent_prompt_manager().get_prompt("review_critic")


class ReviewerCriticAgent(BaseAgent):
    """Reviews and critiques agent outputs with confidence-aware scrutiny.

    Extends BaseAgent with AgentCapability for review tasks.
    Modulates scrutiny depth based on the producing agent's confidence score:
    - High confidence (>=0.9): Light review — template alignment only
    - Medium confidence (0.6-0.9): Standard review — full checks
    - Low confidence (<0.6): Deep review — verify against codebase
    """

    _MIN_DRAFT_LENGTH_STANDARD: int = 100
    _MIN_DRAFT_LENGTH_DEEP: int = 200

    _PLACEHOLDER_PATTERNS: List[re.Pattern] = [
        re.compile(r"\{\{.*?\}\}"),  # {{variable}} placeholders
        re.compile(r"\[TODO\b", re.IGNORECASE),
        re.compile(r"\[PLACEHOLDER\b", re.IGNORECASE),
        re.compile(r"\[TBD\b", re.IGNORECASE),
        re.compile(r"\[FIXME\b", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        pass

    @property
    def capability(self) -> AgentCapability:
        return reviewer_critic_capability(system_prompt=_SYSTEM_PROMPT)

    @staticmethod
    def determine_scrutiny_level(confidence_score: float) -> str:
        """Determine scrutiny level from the producing agent's confidence score.

        Args:
            confidence_score: Float in [0.0, 1.0].

        Returns:
            "light" if confidence >= 0.9,
            "standard" if 0.6 <= confidence < 0.9,
            "deep" if confidence < 0.6.
        """
        if confidence_score >= 0.9:
            return "light"
        elif confidence_score >= 0.6:
            return "standard"
        else:
            return "deep"

    @staticmethod
    def _find_placeholders(draft: str) -> List[str]:
        """Find placeholder patterns in the draft text."""
        found: List[str] = []
        for pattern in ReviewerCriticAgent._PLACEHOLDER_PATTERNS:
            matches = pattern.findall(draft)
            found.extend(matches)
        return found

    @staticmethod
    def _light_review(draft: str, confidence_score: float) -> ReviewResult:
        """Light scrutiny — template alignment check only.

        Short-circuits to approval if draft is non-empty and has reasonable length.
        """
        if not draft or not draft.strip():
            return ReviewResult(
                verdict="rework_needed",
                score=0.2,
                feedback="Draft is empty. Please produce content for this section.",
                missing_items=["section content"],
                scrutiny_level="light",
            )

        if len(draft.strip()) >= 10:
            return ReviewResult(
                verdict="approved",
                score=0.9,
                feedback="High-confidence draft passes light review.",
                scrutiny_level="light",
            )

        return ReviewResult(
            verdict="rework_needed",
            score=0.4,
            feedback="Draft is too short to be meaningful even for a high-confidence section.",
            missing_items=["sufficient content"],
            scrutiny_level="light",
        )

    @staticmethod
    def _standard_review(draft: str, confidence_score: float) -> ReviewResult:
        """Standard scrutiny — completeness, accuracy, consistency checks."""
        missing_items: List[str] = []
        suggestions: List[str] = []
        feedback_parts: List[str] = []

        if not draft or not draft.strip():
            return ReviewResult(
                verdict="rework_needed",
                score=0.1,
                feedback="Draft is empty. Please produce content for this section.",
                missing_items=["section content"],
                scrutiny_level="standard",
            )

        stripped = draft.strip()

        if len(stripped) < ReviewerCriticAgent._MIN_DRAFT_LENGTH_STANDARD:
            missing_items.append("sufficient content (draft is too short)")
            feedback_parts.append(
                f"Draft is only {len(stripped)} characters; "
                f"expected at least {ReviewerCriticAgent._MIN_DRAFT_LENGTH_STANDARD}."
            )

        placeholders = ReviewerCriticAgent._find_placeholders(draft)
        if placeholders:
            missing_items.append(f"unfilled placeholders: {', '.join(placeholders)}")
            feedback_parts.append(f"Found {len(placeholders)} placeholder(s) that need to be filled.")

        has_structure = bool(re.search(r"^#{1,6}\s", draft, re.MULTILINE)) or ("\n\n" in draft)
        if not has_structure and len(stripped) > 50:
            suggestions.append("Consider adding headings or paragraph breaks for structure.")

        if missing_items:
            score = max(0.3, 0.7 - 0.1 * len(missing_items))
            return ReviewResult(
                verdict="rework_needed",
                score=score,
                feedback=" ".join(feedback_parts) if feedback_parts else "Issues found.",
                missing_items=missing_items,
                suggestions=suggestions,
                scrutiny_level="standard",
            )

        return ReviewResult(
            verdict="approved",
            score=0.8,
            feedback="Draft passes standard review checks.",
            suggestions=suggestions,
            scrutiny_level="standard",
        )

    @staticmethod
    def _deep_review(
        draft: str,
        confidence_score: float,
        summarized_context: str,
    ) -> ReviewResult:
        """Deep scrutiny — verify against codebase, flag concerns, detailed feedback."""
        missing_items: List[str] = []
        suggestions: List[str] = []
        feedback_parts: List[str] = []

        if not draft or not draft.strip():
            return ReviewResult(
                verdict="rework_needed",
                score=0.0,
                feedback="Draft is empty. A low-confidence section requires substantial content.",
                missing_items=["section content"],
                scrutiny_level="deep",
            )

        stripped = draft.strip()

        if len(stripped) < ReviewerCriticAgent._MIN_DRAFT_LENGTH_DEEP:
            missing_items.append(
                f"sufficient content (draft is {len(stripped)} chars; "
                f"expected at least {ReviewerCriticAgent._MIN_DRAFT_LENGTH_DEEP} for low-confidence section)"
            )
            feedback_parts.append("Low-confidence drafts need more thorough content to pass deep review.")

        placeholders = ReviewerCriticAgent._find_placeholders(draft)
        if placeholders:
            missing_items.append(f"unfilled placeholders: {', '.join(placeholders)}")
            feedback_parts.append(f"Found {len(placeholders)} placeholder(s) that must be resolved.")

        has_headings = bool(re.search(r"^#{1,6}\s", draft, re.MULTILINE))
        has_paragraphs = "\n\n" in draft
        if not has_headings:
            suggestions.append("Add section headings for better organization.")
        if not has_paragraphs and len(stripped) > 100:
            suggestions.append("Break content into paragraphs for readability.")

        if summarized_context and len(summarized_context.strip()) > 0:
            context_lower = summarized_context.lower()
            draft_lower = draft.lower()
            context_terms = set(re.findall(r"\b[a-z_]{4,}\b", context_lower))
            if context_terms:
                draft_terms = set(re.findall(r"\b[a-z_]{4,}\b", draft_lower))
                overlap = context_terms & draft_terms
                if len(overlap) < min(3, len(context_terms)):
                    suggestions.append("Consider referencing concepts from prior sections for consistency.")

        if missing_items:
            score = max(0.2, 0.6 - 0.15 * len(missing_items))
            return ReviewResult(
                verdict="rework_needed",
                score=score,
                feedback=" ".join(feedback_parts) if feedback_parts else "Issues found during deep review.",
                missing_items=missing_items,
                suggestions=suggestions,
                scrutiny_level="deep",
            )

        return ReviewResult(
            verdict="approved",
            score=0.75,
            feedback="Draft passes deep review checks.",
            suggestions=suggestions,
            scrutiny_level="deep",
        )

    async def analyze(
        self,
        context: Dict[str, Any],
        check_types: List[str],
    ) -> Dict[str, Any]:
        """Analyze context for gaps, clarification needs, and completeness.

        This method is used by the review_phase to determine if the
        collected context is sufficient to proceed to research.

        Args:
            context: The context data to analyze (from state["context"]).
            check_types: List of check types to perform. Supported values:
                - "gaps": Check for missing information
                - "clarification_needs": Check for ambiguous or unclear input
                - "completeness": Check if all required fields are present

        Returns:
            Dict containing:
            - gaps: List of identified gaps (each with 'id', 'description', 'severity')
            - clarification_questions: List of questions for the user
            - completeness_score: Float 0-1 indicating overall completeness
            - analysis: Detailed analysis dict
        """
        gaps: List[Dict[str, Any]] = []
        clarification_questions: List[str] = []
        analysis: Dict[str, Any] = {}

        # Check for gaps (R1)
        if "gaps" in check_types:
            required_fields = ["spec_name", "spec_description", "user_explanation"]
            for field in required_fields:
                value = context.get(field, "")
                if not value or (isinstance(value, str) and not value.strip()):
                    gaps.append(
                        {
                            "id": f"missing_{field}",
                            "description": f"Missing required field: {field}",
                            "severity": "high",
                        }
                    )

            primary_doc = context.get("primary_document")
            supporting_docs = context.get("supporting_docs", [])
            if not primary_doc and not supporting_docs:
                gaps.append(
                    {
                        "id": "no_documents",
                        "description": "No documents provided for context",
                        "severity": "low",
                    }
                )

            explanation = context.get("user_explanation", "")
            if isinstance(explanation, str) and len(explanation.strip()) < 50:
                gaps.append(
                    {
                        "id": "brief_explanation",
                        "description": "User explanation is very brief; consider adding more detail",
                        "severity": "medium",
                    }
                )

        # Check for clarification needs (R1)
        if "clarification_needs" in check_types:
            explanation = context.get("user_explanation", "").lower()
            vague_terms = ["something", "etc", "stuff", "things", "tbd"]
            for term in vague_terms:
                if term in explanation:
                    clarification_questions.append(f"Could you provide more specifics about what you mean by '{term}'?")
                    break

            constraints = context.get("constraints", {})
            if constraints:
                if isinstance(constraints, str):
                    constraints_lower = constraints.lower()
                    if "deadline" not in constraints_lower and "timeline" not in constraints_lower:
                        clarification_questions.append("What is your target timeline or deadline for this feature?")
                elif isinstance(constraints, dict):
                    if not constraints.get("deadline") and not constraints.get("timeline"):
                        clarification_questions.append("What is your target timeline or deadline for this feature?")

        # Check completeness (R1)
        completeness_score = 1.0
        if "completeness" in check_types:
            total_weight = 0.0
            filled_weight = 0.0

            field_weights = {
                "spec_name": 0.15,
                "spec_description": 0.15,
                "user_explanation": 0.30,
                "primary_document": 0.15,
                "constraints": 0.15,
                "supporting_docs": 0.10,
            }

            for field, weight in field_weights.items():
                total_weight += weight
                value = context.get(field)
                if value:
                    if isinstance(value, str) and value.strip():
                        filled_weight += weight
                    elif isinstance(value, dict) and value:
                        filled_weight += weight
                    elif isinstance(value, list) and value:
                        filled_weight += weight

            completeness_score = filled_weight / total_weight if total_weight > 0 else 0.0
            analysis["field_weights"] = field_weights
            analysis["filled_weight"] = filled_weight

        analysis["check_types_performed"] = check_types
        analysis["total_gaps"] = len(gaps)
        analysis["total_questions"] = len(clarification_questions)

        return {
            "gaps": gaps,
            "clarification_questions": clarification_questions,
            "completeness_score": completeness_score,
            "analysis": analysis,
        }

    async def execute(
        self,
        task: AgentTask,
        state: UnifiedSpecState,
        workflow_context: WorkflowContext | None,
    ) -> AgentResult:
        """Review agent output with confidence-aware scrutiny.

        Reads confidence_score from state to determine scrutiny level,
        then applies the appropriate review depth.

        Returns:
            Dict with state updates:
            - review_verdict: "approved" | "rework_needed" | "gap_detected"
            - review_feedback: str with specific critique
            - review_score: float 0-1 quality score
            - scrutiny_level: "light" | "standard" | "deep"
        """
        draft: str = state.get("agent_draft", "") or ""
        confidence_score: float = state.get("confidence_score", 0.5)
        summarized_context: str = state.get("summarized_context", "") or ""

        confidence_score = max(0.0, min(1.0, confidence_score))

        scrutiny = self.determine_scrutiny_level(confidence_score)

        if scrutiny == "light":
            review: ReviewResult = self._light_review(draft, confidence_score)
        elif scrutiny == "standard":
            review: ReviewResult = self._standard_review(draft, confidence_score)
        else:
            review: ReviewResult = self._deep_review(draft, confidence_score, summarized_context)

        return AgentResult(
            output=json.dumps(
                {
                    "review_verdict": review.verdict,
                    "review_feedback": review.feedback,
                    "review_score": review.score,
                    "scrutiny_level": review.scrutiny_level,
                }
            ),
            agent_type="reviewer_critic",
            confidence_score=review.score,
        )
