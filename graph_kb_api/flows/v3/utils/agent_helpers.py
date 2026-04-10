"""Shared utility functions for agent implementations.

These helpers are used across multiple agents for common operations
like computing confidence scores and building prompts.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from graph_kb_api.flows.v3.models.types import AgentTask
from graph_kb_api.flows.v3.utils.prompt_extensions import (
    build_already_covered_block,
    build_scope_contract_block,
)


def compute_confidence(agent_context: Dict[str, Any]) -> Tuple[float, str]:
    """Compute confidence score based on available context.

    Heuristic:
    - Base confidence: 0.7
    - +0.1 if agent_context has relevant KB results
    - +0.1 if agent_context has section_summaries from prior sections
    - +0.05 if nested context has spec_name or research_summary
    - Clamped to [0.0, 1.0]

    Args:
        agent_context: Context dictionary (may have nested "context" key
                       from DispatchNode).

    Returns:
        Tuple of (confidence_score, confidence_rationale).
    """
    if not agent_context:
        return (0.5, "No agent context provided; operating with minimal information.")

    score = 0.7
    reasons: list[str] = ["Base confidence: 0.7"]

    # Check both top-level and nested "context" key (DispatchNode nests under "context")
    nested = agent_context.get("context", {})
    kb_results = agent_context.get("kb_results") or nested.get("kb_results")
    if kb_results:
        score += 0.1
        reasons.append("+0.1 for available KB results")

    section_summaries = agent_context.get("section_summaries") or nested.get("section_summaries")
    if section_summaries:
        score += 0.1
        reasons.append("+0.1 for prior section summaries")

    # Bonus for having spec/research context from FetchContextNode
    if nested.get("spec_name") or nested.get("research_summary"):
        score += 0.05
        reasons.append("+0.05 for available spec/research context")

    score = max(0.0, min(1.0, score))
    return (score, "; ".join(reasons))


def build_prompt(task: AgentTask, agent_context: Dict[str, Any]) -> str:
    """Build the user prompt from task description and available context.

    Reads from both top-level keys (legacy rework flow) and the nested
    ``agent_context["context"]`` dict that DispatchNode populates from
    FetchContextNode data.

    Args:
        task: Task dictionary with description, title, etc.
        agent_context: Context dictionary with kb_results, section_summaries,
                       review_feedback, rework_instructions, etc.  DispatchNode
                       nests FetchContextNode output under the ``"context"`` key.

    Returns:
        Formatted prompt string for the LLM.
    """
    parts: list[str] = []

    description = task.get("description", "")
    if description:
        parts.append(f"## Task\n{description}")

    title = task.get("title", "")
    if title:
        parts.append(f"## Section Title\n{title}")

    # --- DispatchNode-provided context (under nested "context" key) ---
    nested = agent_context.get("context", {})

    # Spec context from FetchContextNode
    spec_name = nested.get("spec_name") or agent_context.get("spec_name", "")
    spec_desc = nested.get("spec_description") or agent_context.get("spec_description", "")
    user_explanation = nested.get("user_explanation") or agent_context.get("user_explanation", "")
    constraints = nested.get("constraints") or agent_context.get("constraints", "")
    if spec_name or spec_desc:
        parts.append(f"## Feature Specification\nName: {spec_name}\nDescription: {spec_desc}")
    if user_explanation:
        parts.append(f"## User Explanation\n{user_explanation}")
    if constraints:
        parts.append(f"## Constraints\n{constraints}")

    spec_section = nested.get("spec_section") or agent_context.get("spec_section", "")
    spec_section_content = nested.get("spec_section_content") or agent_context.get("spec_section_content", "")
    if spec_section and spec_section_content:
        parts.append(f"## Original Specification Section: {spec_section}\n{spec_section_content}")

    # Research findings from FetchContextNode
    research_summary = nested.get("research_summary") or agent_context.get("research_summary", "")
    key_insights = nested.get("key_insights") or agent_context.get("key_insights", [])
    if research_summary:
        parts.append(f"## Research Findings\n{research_summary}")
    if key_insights:
        parts.append(f"## Key Insights\n" + "\n".join(f"- {i}" for i in key_insights))

    # Supporting document sections from FetchContextNode
    supporting_docs = nested.get("supporting_doc_sections", [])
    if supporting_docs:
        doc_parts: list[str] = []
        for doc in supporting_docs:
            doc_parts.append(f"### {doc['filename']}")
            for sec in doc.get("sections", []):
                doc_parts.append(f"#### {sec['heading']}\n{sec['content']}")
        parts.append("## Supporting Documents\n" + "\n\n".join(doc_parts))

    # Hydrated artifacts from ArtifactService
    for key, value in nested.items():
        if key.startswith("artifact_") and value:
            parts.append(f"## Artifact: {key}\n{json.dumps(value, indent=2, default=str)}")

    # Task-level research (from TaskResearchNode)
    task_research = nested.get("task_research", {})
    if task_research and task_research.get("summary"):
        parts.append(f"## Task-Specific Research\n{task_research['summary']}")

    # --- Legacy fields for rework flow ---
    kb_results = agent_context.get("kb_results")
    if kb_results:
        parts.append(f"## Codebase Context\n{kb_results}")

    section_summaries = agent_context.get("section_summaries")
    if section_summaries:
        summaries_text = "\n".join(f"- **{sid}**: {summary}" for sid, summary in section_summaries.items())
        parts.append(f"## Prior Section Summaries\n{summaries_text}")

    review_feedback = agent_context.get("review_feedback")
    if review_feedback:
        parts.append(f"## Reviewer Feedback (address these points)\n{review_feedback}")

    rework_instructions = agent_context.get("rework_instructions")
    if rework_instructions:
        parts.append(f"## Rework Instructions\n{rework_instructions}")

    # --- Scope contract and prior summary blocks (near end for recency bias) ---
    scope_contract = agent_context.get("scope_contract")
    scope_block = build_scope_contract_block(scope_contract) if scope_contract else ""
    if scope_block:
        parts.append(scope_block)

    prior_summary = agent_context.get("prior_sections_summary")
    already_covered_block = build_already_covered_block(prior_summary) if prior_summary else ""
    if already_covered_block:
        parts.append(already_covered_block)

    return "\n\n".join(parts) if parts else "Generate the requested section."
