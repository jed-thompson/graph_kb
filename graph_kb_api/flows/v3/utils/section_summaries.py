"""Section summary extraction utility.

Extracts section titles and truncated first paragraphs for use in
lightweight LLM executive summary passes.

Extracted as a standalone module to avoid heavy import chains in tests.
"""

from __future__ import annotations


def extract_section_summaries(
    ordered_keys: list[str],
    hydrated_sections: dict[str, str],
    max_chars_per_section: int = 300,
) -> str:
    """Extract title + first paragraph from each section for LLM summary pass.

    Returns a string with one entry per section::

        ### {key}
        {first_paragraph_truncated}

    Each section's content is truncated to *max_chars_per_section* characters.
    The total output is suitable for a ~2K token LLM call (roughly
    ``len(ordered_keys) * max_chars_per_section``).

    Args:
        ordered_keys: Non-empty list of section keys; all must exist in
            *hydrated_sections*.
        hydrated_sections: Mapping of section key to full section content.
        max_chars_per_section: Positive integer cap on each section's
            extracted text.

    Returns:
        Concatenated summaries string.
    """
    parts: list[str] = []
    for key in ordered_keys:
        content = hydrated_sections.get(key, "")
        # Take the first paragraph (up to first double-newline)
        first_para = content.split("\n\n", 1)[0].strip()
        if len(first_para) > max_chars_per_section:
            first_para = first_para[:max_chars_per_section]
        parts.append(f"### {key}\n{first_para}\n\n")
    return "".join(parts)
