"""
Final assembly node for the feature spec workflow.

Collects all entries from ``completed_sections`` and assembles them into a
single markdown document following the original template structure (section
ordering, heading levels).  Generates valid cross-references between sections
and sets ``final_output`` to the complete markdown string.

Requirements traced: 18.1, 18.2, 18.3, 18.4
"""

import re
from typing import Any, Dict, List

from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3

# Pattern to detect section references like [see Architecture](#architecture)
_SECTION_REF_RE = re.compile(r"\[([^\]]*)\]\(#([a-z][a-z0-9_]*)\)")


def _section_anchor(section_id: str) -> str:
    """Return a markdown-compatible anchor for a section_id."""
    return section_id.replace("_", "-")


def _build_cross_references(content: str, section_ids: set[str]) -> str:
    """Inject valid markdown anchor links for cross-references.

    Scans for ``[text](#anchor)`` patterns and ensures the anchor matches a
    known section.  Also converts bare ``{{ref:section_id}}`` markers into
    proper links.
    """

    # Convert {{ref:section_id}} markers into markdown links
    def _replace_ref(m: re.Match) -> str:
        sid = m.group(1)
        if sid in section_ids:
            anchor = _section_anchor(sid)
            title = sid.replace("_", " ").title()
            return f"[{title}](#{anchor})"
        return m.group(0)  # leave unresolved refs as-is

    content = re.sub(r"\{\{ref:(\w+)\}\}", _replace_ref, content)
    return content


class FinalAssemblyNode(BaseWorkflowNodeV3):
    """Assembles all completed sections into the final spec document.

    The node reads ``completed_sections`` and ``template_sections`` from
    state, orders the sections according to the original template, applies
    heading levels, generates cross-references, and writes the result to
    ``final_output``.
    """

    def __init__(self) -> None:
        super().__init__("final_assembly")

    async def _execute_async(
        self, state: Dict[str, Any], services: ServiceRegistry
    ) -> NodeExecutionResult:
        self.logger.info("FinalAssemblyNode: assembling final document")

        completed_sections: Dict[str, str] = state.get("completed_sections", {}) or {}
        template_sections: List[Dict[str, Any]] = (
            state.get("template_sections", []) or []
        )

        # Determine section ordering from template_sections (preserves original order)
        ordered_ids: List[str] = [ts["section_id"] for ts in template_sections]

        # Collect heading levels from template (default to 2)
        heading_levels: Dict[str, int] = {}
        for ts in template_sections:
            heading_levels[ts["section_id"]] = ts.get("level", 2)

        # Include any completed sections not in the template at the end
        extra_ids = [sid for sid in completed_sections if sid not in ordered_ids]
        ordered_ids.extend(extra_ids)

        all_section_ids = set(ordered_ids)

        # --- Build table of contents ---
        toc_lines: List[str] = ["## Table of Contents", ""]
        for sid in ordered_ids:
            if sid in completed_sections:
                title = sid.replace("_", " ").title()
                # Try to extract actual title from template_sections
                for ts in template_sections:
                    if ts["section_id"] == sid:
                        title = ts.get("title", title)
                        break
                anchor = _section_anchor(sid)
                toc_lines.append(f"- [{title}](#{anchor})")
        toc_lines.append("")

        # --- Assemble sections ---
        body_lines: List[str] = []
        for sid in ordered_ids:
            content = completed_sections.get(sid)
            if content is None:
                continue

            level = heading_levels.get(sid, 2)
            heading_prefix = "#" * level

            # Determine title
            title = sid.replace("_", " ").title()
            for ts in template_sections:
                if ts["section_id"] == sid:
                    title = ts.get("title", title)
                    break

            # Apply cross-references
            content = _build_cross_references(content, all_section_ids)

            body_lines.append(f"{heading_prefix} {title}")
            body_lines.append("")
            body_lines.append(content)
            body_lines.append("")

        # --- Combine ---
        final_output = "\n".join(toc_lines) + "\n".join(body_lines)

        self.logger.info(
            f"FinalAssemblyNode: assembled {len(completed_sections)} sections "
            f"into {len(final_output)} characters"
        )

        return NodeExecutionResult.success(
            output={
                "final_output": final_output,
            }
        )
