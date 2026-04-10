"""Utility functions for handling workflow context."""

from __future__ import annotations

import logging
from typing import Any, cast

from graph_kb_api.flows.v3.state import ContextData, ResearchData
from graph_kb_api.flows.v3.state.plan_state import ContextItemsSummary

logger = logging.getLogger(__name__)

# Canonical field mapping — applied once at workflow boundary.
# Keys are legacy/alias names; values are the canonical (ID-based) names.
_FIELD_ALIASES: dict[str, str] = {
    "primary_document": "primary_document_id",
    "supporting_docs": "supporting_document_ids",
    # Add future aliases here
}

# Reverse mapping for resolve helpers (canonical → list of aliases)
_CANONICAL_TO_ALIASES: dict[str, list[str]] = {}
for _alias, _canonical in _FIELD_ALIASES.items():
    _CANONICAL_TO_ALIASES.setdefault(_canonical, []).append(_alias)


def resolve_primary_document_id(context: dict[str, Any]) -> str:
    """Resolve the primary document ID from context, checking canonical and alias keys."""
    return (
        context.get("primary_document_id")
        or context.get("primary_document")
        or ""
    )


def resolve_supporting_document_ids(context: dict[str, Any]) -> list[str]:
    """Resolve supporting document IDs from context, checking canonical and alias keys."""
    return list(
        context.get("supporting_document_ids")
        or context.get("supporting_doc_ids")
        or context.get("supporting_docs")
        or []
    )


def resolve_extracted_urls(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve extracted URLs from context, preferring artifact-backed metadata.

    Returns a list of ``{"url": ...}`` dicts suitable for the frontend
    ``ContextItemsPanel``.  Handles three source formats:

    1. ``reference_urls_meta`` — rich metadata from scraped URL documents (preferred)
    2. ``extracted_urls`` / ``reference_urls`` — plain URL strings or dicts
    3. Comma-separated string (legacy)
    """
    url_meta = context.get("reference_urls_meta")
    if url_meta:
        return url_meta  # type: ignore[return-value]

    raw = context.get("extracted_urls") or context.get("reference_urls") or []
    if isinstance(raw, str):
        raw = [u.strip() for u in raw.split(",") if u.strip()]
    if not raw:
        return []
    return [u if isinstance(u, dict) else {"url": u} for u in raw]


def build_context_items_for_display(context: dict[str, Any]) -> ContextItemsSummary:
    """Build a ``ContextItemsSummary`` from raw context state for frontend display.

    Single source of truth for extracting the fields that the frontend
    ``ContextItemsPanel`` needs.  Used by ``FeedbackReviewNode`` and
    ``PlanDispatcher._build_context_items_snapshot``.
    """
    items: ContextItemsSummary = {}

    urls = resolve_extracted_urls(context)
    if urls:
        items["extracted_urls"] = urls  # type: ignore[assignment]

    rounds = context.get("rounds", [])
    if rounds:
        items["rounds"] = rounds  # type: ignore[assignment]

    primary_doc_id = resolve_primary_document_id(context)
    if primary_doc_id:
        items["primary_document_id"] = primary_doc_id

    supporting_ids = resolve_supporting_document_ids(context)
    if supporting_ids:
        items["supporting_doc_ids"] = supporting_ids

    user_explanation = context.get("user_explanation", "")
    if user_explanation:
        items["user_explanation"] = user_explanation

    return items


def normalize_context_names(context: ContextData | None) -> ContextData:
    """Normalize document reference field names to canonical form.

    Applied once at the workflow entry point (PlanEngine._build_initial_state).
    If both alias and canonical name exist, prefers the canonical (ID-based)
    form and logs a deprecation warning.

    Args:
        context: Raw context dict from user input.

    Returns:
        Context dict with all field names in canonical form.
    """
    if not context:
        return ContextData()

    result: ContextData = cast(ContextData, dict(context))

    for alias, canonical in _FIELD_ALIASES.items():
        if alias not in result:
            continue

        alias_value = result.pop(alias)  # type: ignore[misc]

        if canonical in result:
            # Both present — prefer canonical, log deprecation warning
            logger.warning(
                "Context contains both '%s' and '%s'; "
                "using canonical '%s'. The alias '%s' is deprecated.",
                alias,
                canonical,
                canonical,
                alias,
            )
        else:
            # Only alias present — promote to canonical name
            result[canonical] = alias_value  # type: ignore[literal-required]

    return result


# Fields explicitly excluded from the lightweight summary.
# These contain large payloads (raw file contents, full analysis reports)
# that should never appear in interrupt payloads or DB snapshots.
_BULKY_CONTEXT_FIELDS: frozenset[str] = frozenset({
    "uploaded_document_contents",
    "document_section_index",
    "reference_documents",
    "deep_analysis_full",
})


def build_context_items_summary(
    session_id: str | None,
    research: ResearchData,
    context: ContextData,
) -> ContextItemsSummary:
    """Build a lightweight context items summary for approval payloads and DB snapshots.

    Consolidates the 5 existing normalization paths into one. Excludes bulky
    fields listed in _BULKY_CONTEXT_FIELDS.

    Args:
        session_id: Current session ID (reserved for future artifact lookups).
        research: Research phase data dict.
        context: Context phase data dict.

    Returns:
        Normalized context items dict suitable for interrupt payloads and DB storage.
    """
    if not context and not research:
        return ContextItemsSummary()

    # Start from a shallow copy of context, stripping bulky fields
    ctx_dict: ContextItemsSummary = cast(ContextItemsSummary, {
        k: v for k, v in (context or {}).items() if k not in _BULKY_CONTEXT_FIELDS
    })

    # Merge research findings doc ID into supporting_doc_ids
    research_doc_id: str | None = research.get("findings_doc_id") if research else None
    if research_doc_id:
        supporting: list[str] = list(ctx_dict.get("supporting_doc_ids", []))
        if research_doc_id not in supporting:
            supporting.append(research_doc_id)
            ctx_dict["supporting_doc_ids"] = supporting

    return ctx_dict


def sanitize_context_for_prompt(context: ContextData | None) -> dict[str, Any]:
    """Sanitize workflow context data before injecting into LLM prompts.

    Removes large nested structures like full document contents and section indexes
    that should be formatted and appended explicitly instead of being dumped within
    the raw context JSON block. This preserves token budget and prevents redundant
    injections.

    Args:
        context: The raw context dictionary.

    Returns:
        A shallow copy of the context with bulky fields removed.
    """
    if not context:
        return {}

    sanitized = context.copy()

    # Remove extremely bulky fields that contain raw file contents or comprehensive indexes
    bulky_keys = [
        "uploaded_document_contents",
        "document_section_index",
        "reference_documents",
        "extracted_urls",  # Usually not strictly needed if reference_urls_meta is present
    ]

    for key in bulky_keys:
        sanitized.pop(key, None)

    return sanitized


def append_document_context_to_prompt(prompt: str, context: ContextData, include_full: bool = True) -> str:
    """Append uploaded documents and section index to prompt.

    Args:
        prompt: The markdown prompt to append to.
        context: The workflow context dictionary containing document data.
        include_full: Whether to include the full truncated text of documents,
                      or just the section indexes.

    Returns:
        The prompt string with document contexts appended.
    """
    doc_contents = context.get("uploaded_document_contents", [])
    if doc_contents and include_full:
        from graph_kb_api.flows.v3.utils.document_content_reader import format_documents_for_prompt

        docs_str: str = format_documents_for_prompt(doc_contents)
        if docs_str:
            prompt += f"\n\n{docs_str}\n"

    section_index = context.get("document_section_index", [])
    if section_index:
        prompt += "\n## Document Section Index\n\n"
        for doc in section_index:
            role_label = doc.get("role", "supporting")
            filename = doc.get("filename", "unknown")
            prompt += f"### {filename} ({role_label})\n"
            for sec in doc.get("sections", []):
                level = sec.get("level", 1)
                indent = "  " * (level - 1)
                heading = sec.get("heading", "Untitled")
                prompt += f"{indent}- {heading}\n"
            prompt += "\n"

    return prompt
