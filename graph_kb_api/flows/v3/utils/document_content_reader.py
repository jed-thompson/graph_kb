"""Utility for reading uploaded document content from blob storage.

Loads document content by doc_id, handles text decoding and token-budget
truncation, and returns structured dicts suitable for injection into LLM
prompts via the ``uploaded_document_contents`` key on ``ContextData``.

Also provides section-chunking utilities for building a composite
document section index that enables per-task scoped loading of
requirements documents.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Literal, Optional

from graph_kb_api.database.base import get_db_session_ctx
from graph_kb_api.database.document_models import UploadedDocument
from graph_kb_api.database.document_repositories import DocumentRepository
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator, truncate_to_tokens
from graph_kb_api.storage import Artifact
from graph_kb_api.storage.blob_storage import BlobStorage

logger = logging.getLogger(__name__)

# --- Constants ---------------------------------------------------------------

TEXT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/html",
        "application/json",
        "text/csv",
        "text/x-yaml",
        "text/yaml",
        "application/yaml",
        "application/xml",
        "text/xml",
    }
)

PRIMARY_DOC_TOKEN_BUDGET: int = 200_000
SUPPORTING_DOC_TOKEN_BUDGET: int = 200_000
MAX_TOTAL_UPLOADED_TOKENS: int = 200_000


# --- Public API --------------------------------------------------------------


async def load_uploaded_document_contents(
    doc_ids: List[str],
    role: str = "supporting",
    max_tokens_per_doc: int = SUPPORTING_DOC_TOKEN_BUDGET,
    total_token_cap: int = MAX_TOTAL_UPLOADED_TOKENS,
) -> List[Dict[str, str]]:
    """Read document content from blob storage for LLM prompt injection.

    For each *doc_id* the function looks up the ``UploadedDocument`` record,
    checks that the MIME type is text-parseable, retrieves content from blob
    storage, decodes if necessary, and truncates to *max_tokens_per_doc*
    using tiktoken-based truncation.

    Args:
        doc_ids: Document UUIDs to load.
        role: ``"primary"`` or ``"supporting"`` — stored in the result for
              downstream prompt labelling.
        max_tokens_per_doc: Token budget applied to each individual document.
        total_token_cap: Hard cap on combined tokens across all documents.
            When exceeded, remaining documents are skipped.

    Returns:
        List of dicts with keys ``doc_id``, ``filename``, ``content``, ``role``.
        Documents that cannot be read (missing, non-text MIME, decode error)
        are silently skipped with a warning log.
    """
    if not doc_ids:
        return []

    results: List[Dict[str, str]] = []
    tokens_used = 0

    try:
        storage: BlobStorage = BlobStorage.from_env()
    except Exception as e:
        logger.warning("document_content_reader: failed to initialise BlobStorage: %s", e)
        return []

    for doc_id in doc_ids:
        if not doc_id or tokens_used >= total_token_cap:
            continue

        try:
            async with get_db_session_ctx() as db_session:
                doc_repo = DocumentRepository(db_session)
                doc: UploadedDocument | None = await doc_repo.get(doc_id)

            if doc is None:
                logger.warning("document_content_reader: document %s not found in DB", doc_id)
                continue

            is_text_mime = doc.mime_type in TEXT_MIME_TYPES
            is_text_ext = bool(doc.original_filename and doc.original_filename.lower().endswith((".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".xml")))

            if not is_text_mime and not is_text_ext:
                logger.warning(
                    "document_content_reader: skipping %s (mime_type=%s, filename=%s) — not text-parseable",
                    doc_id,
                    doc.mime_type,
                    doc.original_filename,
                )
                continue

            artifact: Artifact | None = await storage.backend.retrieve(doc.storage_key)
            if artifact is None:
                logger.warning(
                    "document_content_reader: blob content not found for %s (key=%s)",
                    doc_id,
                    doc.storage_key,
                )
                continue

            raw_content: str
            if isinstance(artifact.content, bytes):
                raw_content = artifact.content.decode("utf-8", errors="replace")
            elif isinstance(artifact.content, str):
                raw_content = artifact.content
            else:
                raw_content = str(artifact.content)

            # Respect per-document budget and remaining total budget
            remaining_budget: int = total_token_cap - tokens_used
            effective_budget: int = min(max_tokens_per_doc, remaining_budget)
            content = truncate_to_tokens(raw_content, effective_budget)
            tokens_used += _estimate_tokens(content)

            results.append(
                {
                    "doc_id": doc_id,
                    "filename": doc.original_filename,
                    "content": content,
                    "role": role,
                }
            )

            logger.info(
                "document_content_reader: loaded %s (%s, %d chars) as %s",
                doc_id,
                doc.original_filename,
                len(content),
                role,
            )

        except Exception as e:
            logger.warning("document_content_reader: failed to read %s: %s", doc_id, e)

    return results


# --- Helpers -----------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Estimate token count using the project's TokenEstimator (tiktoken-based)."""
    return get_token_estimator().count_tokens(text)


def format_documents_for_prompt(
    documents: List[Dict[str, str]],
    max_tokens: int = MAX_TOTAL_UPLOADED_TOKENS,
) -> str:
    """Format a list of document dicts into a markdown section for LLM prompts.

    Args:
        documents: Output from ``load_uploaded_document_contents()``.
        max_tokens: Token budget for the combined output.

    Returns:
        Markdown string with one ``###`` section per document, or empty string
        if *documents* is empty.
    """
    if not documents:
        return ""

    parts: list[str] = []
    tokens_used = 0

    for doc in documents:
        role_label: Literal["Primary Requirements Document", "Supporting Document"] = (
            "Primary Requirements Document" if doc.get("role") == "primary" else "Supporting Document"
        )
        filename: str = doc.get("filename", "unknown")
        content: str = doc.get("content", "")

        header = f"### {role_label}: {filename}"
        section_tokens = _estimate_tokens(f"{header}\n\n{content}")

        if tokens_used + section_tokens > max_tokens:
            remaining: int = max_tokens - tokens_used
            if remaining > 100:
                content = truncate_to_tokens(content, remaining)
                section_tokens = _estimate_tokens(f"{header}\n\n{content}")
            else:
                break

        section = f"{header}\n\n{content}"
        tokens_used += section_tokens
        parts.append(section)

    if not parts:
        return ""

    return "## Uploaded Requirements Documents\n\n" + "\n\n---\n\n".join(parts)


# --- Section Indexing --------------------------------------------------------


# Regex for markdown headings: # Level1, ## Level2, ### Level3, etc.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def build_section_index(content: str, filename: str) -> List[Dict[str, Any]]:
    """Build a section index from markdown headings for per-task chunking.

    Parses ``#`` / ``##`` / ``###`` headings and maps each to a character
    range within *content*.  Non-markdown content (no headings detected)
    falls back to a single entry spanning the full document.

    Returns:
        List of dicts sorted by position::

            [{heading, level, start_char, end_char, token_count}]
    """
    if not content or not content.strip():
        return []

    matches = list(_HEADING_RE.finditer(content))

    if not matches:
        # No markdown headings — return a single entry covering full content.
        return [
            {
                "heading": filename,
                "level": 0,
                "start_char": 0,
                "end_char": len(content),
                "token_count": _estimate_tokens(content),
            }
        ]

    sections: List[Dict[str, Any]] = []
    for i, m in enumerate(matches):
        level = len(m.group(1))  # # → 1, ## → 2, etc.
        heading = m.group(2).strip()
        start_char = m.start()
        end_char = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        # Slice the section body (from after the heading line to end_char).
        # Skip the heading line itself for the body, but keep start_char
        # at the heading position so upstream consumers can reconstruct
        # the full section including the heading.
        section_text = content[start_char:end_char]
        sections.append(
            {
                "heading": heading,
                "level": level,
                "start_char": start_char,
                "end_char": end_char,
                "token_count": _estimate_tokens(section_text),
            }
        )

    return sections


def build_composite_document_index(
    doc_entries: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Build a composite section index across all uploaded documents.

    Args:
        doc_entries: Output from ``load_uploaded_document_contents()``.
            Each dict has keys ``doc_id``, ``filename``, ``content``, ``role``.

    Returns:
        List of per-document index entries::

            [{doc_id, filename, role, sections: [{heading, level, start_char, end_char, token_count}]}]

        Documents that cannot be parsed get an empty ``sections`` list
        and are silently skipped by downstream consumers.
    """
    composite: List[Dict[str, Any]] = []

    for doc in doc_entries:
        doc_id = doc.get("doc_id", "")
        filename = doc.get("filename", "unknown")
        content = doc.get("content", "")
        role = doc.get("role", "supporting")

        sections = build_section_index(content, filename)

        if not sections:
            logger.info(
                "build_composite_document_index: %s (%s, role=%s) → 0 sections, skipping",
                filename,
                doc_id,
                role,
            )
            continue

        composite.append(
            {
                "doc_id": doc_id,
                "filename": filename,
                "role": role,
                "sections": sections,
            }
        )

        logger.info(
            "build_composite_document_index: %s (%s, role=%s) → %d sections",
            filename,
            doc_id,
            role,
            len(sections),
        )

    return composite
