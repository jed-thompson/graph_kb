"""Utility functions for handling workflow context."""

from __future__ import annotations

from typing import Any, Mapping


def sanitize_context_for_prompt(context: dict[str, Any] | None) -> dict[str, Any]:
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


def append_document_context_to_prompt(prompt: str, context: Mapping[str, Any], include_full: bool = True) -> str:
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
