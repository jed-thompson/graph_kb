"""Dedup directive validation utilities.

Validates dedup directives produced by CompositionReviewNode against
a document manifest, dropping invalid directives with warnings.

**Validates: Requirements 8.2, 8.3, 8.4**
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic schema for structured LLM output (OpenAI structured outputs)
# ---------------------------------------------------------------------------


class CompositionReviewIssue(BaseModel):
    """A single issue found during composition review."""

    severity: str = Field(description="Issue severity: 'critical', 'major', 'minor', or 'info'")
    category: str = Field(description="Issue category: 'redundancy', 'terminology', 'cross_reference', 'formatting', 'coverage', 'failed_task'")
    affected_documents: list[str] = Field(default_factory=list, description="List of affected document/task IDs")
    affected_task_ids: list[str] = Field(default_factory=list, description="List of affected task IDs from the manifest")
    description: str = Field(description="Description of the issue")


class CompositionReviewDedupDirective(BaseModel):
    """A dedup directive with enforced field names via structured output."""

    canonical_section: str = Field(description="The task_id of the section that should own the definitive content")
    duplicate_in: list[str] = Field(description="List of task_ids where the content is duplicated")
    topic: str = Field(description="Brief description of what content is duplicated")
    action: str = Field(description="Human-readable instruction for how to resolve the duplication")


class CompositionReviewResponse(BaseModel):
    """Full composition review response schema for structured LLM output.

    Used with ``llm.with_structured_output(CompositionReviewResponse)`` to
    guarantee the LLM returns exactly these field names and types.
    """

    overall_score: float = Field(ge=0.0, le=1.0, description="Quality score from 0.0 to 1.0")
    summary: str = Field(description="Brief assessment of the document suite quality")
    issues: list[CompositionReviewIssue] = Field(default_factory=list, description="List of identified issues")
    needs_re_orchestrate: bool = Field(default=False, description="Whether re-orchestration is needed (only if score < 0.7)")
    recommendations: list[str] = Field(default_factory=list, description="List of recommendations")
    dedup_directives: list[CompositionReviewDedupDirective] = Field(default_factory=list, description="Dedup directives for redundancy resolution")


class DedupDirective(TypedDict):
    """A structured dedup directive from composition review."""

    canonical_section: str
    duplicate_in: list[str]
    topic: str
    action: str


_REQUIRED_FIELDS = ("canonical_section", "duplicate_in", "topic", "action")

# LLMs sometimes use alternate field names. Map common variants to canonical names.
_FIELD_ALIASES: dict[str, str] = {
    "canonical_owner": "canonical_section",
    "canonical": "canonical_section",
    "owner": "canonical_section",
    "replace_with_cross_reference_in": "duplicate_in",
    "duplicates": "duplicate_in",
    "duplicated_in": "duplicate_in",
    "directive": "action",
    "instruction": "action",
    "resolution": "action",
}


def _normalize_field_names(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize alternate LLM field names to the canonical schema."""
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        canonical_key = _FIELD_ALIASES.get(key, key)
        # Don't overwrite if the canonical name is already present
        if canonical_key not in normalized:
            normalized[canonical_key] = value
    return normalized


def _resolve_to_task_id(value: str, section_to_task_id: dict[str, str]) -> str | None:
    """Resolve a value to a task ID.

    Accepts either a task ID directly or a section title that maps to one.
    """
    if value in section_to_task_id:
        # It's already a task ID (task IDs are keys too) or a section title
        return section_to_task_id[value]
    return None


def validate_dedup_directives(
    raw_directives: list[dict[str, Any]],
    manifest_task_ids: set[str],
    section_to_task_id: dict[str, str] | None = None,
) -> list[DedupDirective]:
    """Validate dedup directives against a set of known manifest task IDs.

    For each directive:
    - All four required fields must be present and non-empty.
    - ``canonical_section`` must reference a task ID in *manifest_task_ids*.
    - Every entry in ``duplicate_in`` must reference a task ID in *manifest_task_ids*.
    - ``duplicate_in`` must be a non-empty list.

    When *section_to_task_id* is provided, the validator will attempt to
    resolve section titles to task IDs before checking against the manifest.
    LLM alternate field names (e.g. ``canonical_owner`` instead of
    ``canonical_section``) are also normalized automatically.

    Invalid directives are dropped with a warning log.

    Returns only the directives that pass all checks.
    """
    if section_to_task_id is None:
        section_to_task_id = {}

    valid: list[DedupDirective] = []

    for idx, raw in enumerate(raw_directives):
        if not isinstance(raw, dict):
            logger.warning("Dedup directive %d: not a dict — dropped", idx)
            continue

        # Normalize alternate LLM field names
        raw = _normalize_field_names(raw)

        # Check required fields present and non-empty
        missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            logger.warning(
                "Dedup directive %d: missing or empty fields %s — dropped",
                idx,
                missing,
            )
            continue

        canonical: str = raw["canonical_section"]
        duplicate_in = raw["duplicate_in"]
        topic: str = raw["topic"]
        action: str = raw["action"]

        # canonical_section must be a string
        if not isinstance(canonical, str):
            logger.warning(
                "Dedup directive %d: canonical_section is not a string — dropped",
                idx,
            )
            continue

        # Resolve canonical_section: try as task ID first, then as section title
        if canonical not in manifest_task_ids and section_to_task_id:
            resolved = _resolve_to_task_id(canonical, section_to_task_id)
            if resolved:
                logger.debug(
                    "Dedup directive %d: resolved canonical_section '%s' → '%s'",
                    idx, canonical, resolved,
                )
                canonical = resolved

        # duplicate_in must be a non-empty list of strings
        if not isinstance(duplicate_in, list) or len(duplicate_in) == 0:
            logger.warning(
                "Dedup directive %d: duplicate_in is not a non-empty list — dropped",
                idx,
            )
            continue

        if not all(isinstance(d, str) for d in duplicate_in):
            logger.warning(
                "Dedup directive %d: duplicate_in contains non-string entries — dropped",
                idx,
            )
            continue

        # Resolve duplicate_in entries: try as task IDs first, then as section titles
        if section_to_task_id:
            resolved_dups: list[str] = []
            for d in duplicate_in:
                if d in manifest_task_ids:
                    resolved_dups.append(d)
                else:
                    resolved = _resolve_to_task_id(d, section_to_task_id)
                    if resolved:
                        resolved_dups.append(resolved)
                    else:
                        resolved_dups.append(d)  # keep original, will fail validation below
            duplicate_in = resolved_dups

        # Validate canonical_section exists in manifest
        if canonical not in manifest_task_ids:
            logger.warning(
                "Dedup directive %d: canonical_section '%s' not in manifest — dropped",
                idx,
                canonical,
            )
            continue

        # Validate all duplicate_in entries exist in manifest
        invalid_dups = [d for d in duplicate_in if d not in manifest_task_ids]
        if invalid_dups:
            logger.warning(
                "Dedup directive %d: duplicate_in entries %s not in manifest — dropped",
                idx,
                invalid_dups,
            )
            continue

        valid.append(
            DedupDirective(
                canonical_section=canonical,
                duplicate_in=duplicate_in,
                topic=topic,
                action=action,
            )
        )

    return valid
