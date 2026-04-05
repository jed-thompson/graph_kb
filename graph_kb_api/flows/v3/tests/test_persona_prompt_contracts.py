"""Regression checks for critical persona prompt contracts.

These prompts drive LLM behavior in the planning and multi-agent workflows.
The tests focus on high-value structure instead of exact snapshots so prompt
improvements remain possible without losing the guard rails we need.
"""

from __future__ import annotations

import pytest

from graph_kb_api.flows.v3.agents.personas import get_agent_prompt_manager


PROMPT_SECTION_EXPECTATIONS = {
    ("agents", "tool_planner"): ["## Planning Rules", "## Guardrails"],
    ("agents", "architect"): ["## Mission", "## Grounding Rules", "## Output Expectations"],
    ("agents", "doc_extractor"): ["## Mission", "## Grounding Rules", "## Output Expectations"],
    ("agents", "lead_engineer"): ["## Mission", "## Grounding Rules", "## Output Expectations"],
    ("agents", "consistency_checker"): ["## What To Check", "## Severity Rules", "## Guardrails"],
    ("agents", "review_critic"): ["## Review Priorities", "## Guardrails", "## What Good Feedback Looks Like"],
    ("agents", "researcher_agent"): ["## Mission", "## Evidence Rules", "## Output Expectations"],
    ("agents", "code_generator"): ["## Working Style", "## Guardrails", "## Output Expectations"],
    ("agents", "code_analyst"): ["## Mission", "## Evidence Rules", "## Output Expectations"],
    ("nodes", "assembly_section"): ["## Writing Rules", "## Output Requirements"],
    ("nodes", "task_classifier"): ["## Decision Rules", "## Output Format", "Do not wrap the JSON in markdown fences."],
    ("nodes", "plan_feasibility"): ["## What To Evaluate", "## Guardrails", "Do not include markdown fences or commentary outside the JSON object."],
    ("nodes", "result_aggregation"): ["## Resolution Rules", "object keyed by task ID", "If no conflict can be resolved confidently, return `{}`."],
    ("nodes", "research_aggregate"): ["## Mission", "## Guardrails", "## Output Requirements"],
}


TEMPLATED_PROMPTS = [
    (
        "nodes",
        "assembly_section",
        {
            "section_name": "Architecture",
            "spec_name": "Realtime Search",
            "context_summary": "Relevant modules and system constraints.",
            "findings_summary": "Research findings go here.",
            "task_outputs_summary": "Task outputs go here.",
        },
    ),
    (
        "nodes",
        "task_classifier",
        {
            "agent_types": '{"code_analyst": "analysis", "code_generator": "implementation"}',
        },
    ),
    (
        "nodes",
        "result_aggregation",
        {
            "conflicts": "Conflict 1: Task task_123 disagrees on API naming.",
        },
    ),
]


def test_critical_persona_prompts_keep_structure() -> None:
    """Critical prompts should keep mission, guard rail, and output sections."""
    manager = get_agent_prompt_manager()

    for (subdir, name), expected_sections in PROMPT_SECTION_EXPECTATIONS.items():
        prompt = manager.get_prompt(name, subdir=subdir)
        assert len(prompt.splitlines()) >= 12, f"{subdir}/{name}.md is too short to be a useful contract"
        for expected in expected_sections:
            assert expected in prompt, f"{subdir}/{name}.md is missing required section: {expected!r}"


@pytest.mark.parametrize(("subdir", "name", "variables"), TEMPLATED_PROMPTS)
def test_templated_prompts_render_without_leaving_jinja_placeholders(
    subdir: str,
    name: str,
    variables: dict[str, str],
) -> None:
    """Rendered prompts should not leak unresolved Jinja placeholders."""
    manager = get_agent_prompt_manager()

    rendered = manager.render_prompt(name, subdir=subdir, **variables)

    assert "{{" not in rendered
    assert "}}" not in rendered
