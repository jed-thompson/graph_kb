"""Prior sections summary builder utility.

Builds a compressed bullet summary of completed sections for injection
into the agent prompt, preventing cross-section repetition.

Extracted as a standalone module to avoid heavy import chains in tests.
"""

from __future__ import annotations

from typing import Any


def build_prior_sections_summary(
    task_results: list[dict[str, Any]],
    max_tokens: int = 1500,
    _estimator: Any | None = None,
) -> str:
    """Build compressed bullet summary of completed sections.

    Returns a markdown block suitable for injection into the user prompt.
    Only includes entries where status == "done" and output is non-empty.
    Enforces a token budget, preserving earlier (foundational) sections
    when truncation is needed.

    Args:
        task_results: List of task result dicts with keys id, name, status, output.
        max_tokens: Maximum token budget for the returned summary.
        _estimator: Optional token estimator instance (for testing without heavy imports).

    Returns:
        Markdown string starting with "## Already Covered by Prior Sections\\n",
        or empty string when no completed tasks exist.
    """
    if _estimator is None:
        from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator

        _estimator = get_token_estimator()

    estimator = _estimator
    header = "## Already Covered by Prior Sections\n"
    lines: list[str] = []
    running_tokens = estimator.count_tokens(header)

    for result in task_results:
        if result.get("status") != "done":
            continue
        output = result.get("output", "")
        if not output:
            continue

        name = result.get("name", "Unknown")
        task_id = result.get("id", "unknown")

        # Extract first 2-3 sentences as summary
        sentences = output.replace("\n", " ").split(". ")
        summary = ". ".join(sentences[:3]).strip()
        if len(summary) > 200:
            summary = summary[:200] + "..."

        # Extract open questions if present
        oq_marker = ""
        for marker in [
            "### Open Questions",
            "### Assumptions and Open Questions",
            "## Open Questions",
        ]:
            if marker in output:
                idx = output.index(marker)
                oq_block = output[idx : idx + 300]
                oq_lines = [
                    line.strip()
                    for line in oq_block.split("\n")
                    if line.strip().startswith("- ")
                ]
                if oq_lines:
                    oq_marker = f" Open questions: {'; '.join(oq_lines[:3])}"
                break

        line = f'- Section "{name}" ({task_id}): {summary}{oq_marker}\n'
        line_tokens = estimator.count_tokens(line)

        if running_tokens + line_tokens > max_tokens:
            break  # Preserve earlier (foundational) sections

        lines.append(line)
        running_tokens += line_tokens

    if not lines:
        return ""

    return header + "".join(lines)
