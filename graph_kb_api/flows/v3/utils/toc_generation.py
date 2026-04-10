"""Table of Contents generation utility.

Generates markdown TOC with numbered entries and lowercase-hyphenated anchor links.
Extracted as a standalone module to avoid heavy import chains in tests.
"""

from __future__ import annotations

import re


def generate_toc(ordered_keys: list[str]) -> str:
    """Generate markdown Table of Contents with anchor links.

    Each entry is a numbered line: ``{i}. [{key}](#{anchor})``
    where *anchor* is the key lowercased, with spaces replaced by
    hyphens and dots / special characters removed.

    Args:
        ordered_keys: List of section title strings.

    Returns:
        Markdown TOC string starting with ``## Table of Contents\\n``.
    """
    lines = ["## Table of Contents\n"]
    for i, key in enumerate(ordered_keys, 1):
        anchor = re.sub(r"[^a-z0-9\s-]", "", key.lower()).strip()
        anchor = re.sub(r"\s+", "-", anchor)
        lines.append(f"{i}. [{key}](#{anchor})")
    return "\n".join(lines) + "\n"
