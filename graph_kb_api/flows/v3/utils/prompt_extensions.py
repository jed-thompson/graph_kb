"""Standalone prompt extension utilities for scope contracts and prior summaries.

These functions build markdown blocks that are appended near the end of the
agent prompt, exploiting LLM recency bias for maximum attention.
"""

from __future__ import annotations

from typing import Any


def build_already_covered_block(prior_sections_summary: str) -> str:
    """Build the '## Already Covered' prompt block from a prior sections summary.

    Args:
        prior_sections_summary: Markdown summary text of prior completed sections.

    Returns:
        A formatted '## Already Covered' block, or empty string if input is
        empty/whitespace-only.
    """
    if not prior_sections_summary or not prior_sections_summary.strip():
        return ""
    return f"## Already Covered\n{prior_sections_summary.strip()}"


def build_scope_contract_block(scope_contract: dict[str, Any]) -> str:
    """Build the '## Scope Contract' prompt block from a scope contract dict.

    The scope_contract dict is expected to have:
      - scope_includes: list[str] — topics this section MUST cover
      - scope_excludes: list[str] — topics this section must NOT define
      - cross_cutting_owner: str | None — section ID owning cross-cutting concerns

    Args:
        scope_contract: Scope contract dictionary.

    Returns:
        A formatted '## Scope Contract' block, or empty string if the contract
        is empty or has no actionable content.
    """
    if not scope_contract:
        return ""

    parts: list[str] = ["## Scope Contract"]

    includes = scope_contract.get("scope_includes", [])
    if includes:
        parts.append("### Must Cover")
        for topic in includes:
            parts.append(f"- {topic}")

    excludes = scope_contract.get("scope_excludes", [])
    if excludes:
        cross_cutting_owner = scope_contract.get("cross_cutting_owner")
        if cross_cutting_owner:
            parts.append(
                f"### Must NOT Cover (defined elsewhere — see {cross_cutting_owner})"
            )
        else:
            parts.append("### Must NOT Cover (defined elsewhere)")
        for topic in excludes:
            parts.append(f"- {topic}")

    # Only return if we have at least one sub-section beyond the header
    if len(parts) <= 1:
        return ""

    return "\n".join(parts)
