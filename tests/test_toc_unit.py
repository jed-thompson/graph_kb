"""Unit tests for _generate_toc() anchor generation.

Tests anchor generation with special characters, spaces, dots, and unicode.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4**
"""

from __future__ import annotations

import os
import re
import sys

# Import the standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies.
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from toc_generation import generate_toc as _generate_toc  # noqa: E402

sys.path.pop(0)


_TOC_ENTRY_RE = re.compile(r"^(\d+)\.\s+\[(.+?)\]\(#(.*?)\)$")


def _parse_toc_entries(toc: str) -> list[tuple[int, str, str]]:
    """Parse TOC string into list of (number, display_text, anchor)."""
    entries: list[tuple[int, str, str]] = []
    for line in toc.splitlines():
        m = _TOC_ENTRY_RE.match(line)
        if m:
            entries.append((int(m.group(1)), m.group(2), m.group(3)))
    return entries


class TestTocAnchorGeneration:
    """Unit tests for TOC anchor generation.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    """

    def test_special_characters_removed(self):
        """Special characters (!@#$%) are stripped from anchors.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Error Handling!@#$%"])
        entries = _parse_toc_entries(toc)
        assert len(entries) == 1
        _, display, anchor = entries[0]
        assert display == "Error Handling!@#$%"
        assert anchor == "error-handling"
        assert "!" not in anchor
        assert "@" not in anchor
        assert "#" not in anchor
        assert "$" not in anchor
        assert "%" not in anchor

    def test_spaces_replaced_with_hyphens(self):
        """Spaces in section titles become hyphens in anchors.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Architecture Overview"])
        entries = _parse_toc_entries(toc)
        assert len(entries) == 1
        _, _, anchor = entries[0]
        assert anchor == "architecture-overview"
        assert " " not in anchor

    def test_dots_removed(self):
        """Dots in section titles (e.g., 'Section 1.2') are removed from anchors.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Section 1.2"])
        entries = _parse_toc_entries(toc)
        assert len(entries) == 1
        _, display, anchor = entries[0]
        assert display == "Section 1.2"
        assert anchor == "section-12"
        assert "." not in anchor

    def test_unicode_characters(self):
        """Unicode characters are stripped from anchors.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Résumé Overview"])
        entries = _parse_toc_entries(toc)
        assert len(entries) == 1
        _, display, anchor = entries[0]
        assert display == "Résumé Overview"
        # é is stripped, leaving "rsum overview" -> "rsum-overview"
        assert anchor == "rsum-overview"

    def test_multiple_spaces_collapsed(self):
        """Multiple consecutive spaces become a single hyphen.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Error   Handling"])
        entries = _parse_toc_entries(toc)
        _, _, anchor = entries[0]
        assert anchor == "error-handling"
        assert "--" not in anchor

    def test_mixed_case_lowered(self):
        """Mixed case titles produce lowercase anchors.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Build Purchase Request"])
        entries = _parse_toc_entries(toc)
        _, _, anchor = entries[0]
        assert anchor == "build-purchase-request"

    def test_numbering_sequential(self):
        """Multiple entries are numbered sequentially starting from 1.

        **Validates: Requirements 6.1, 6.4**
        """
        keys = ["Architecture", "Authentication", "Validation"]
        toc = _generate_toc(keys)
        entries = _parse_toc_entries(toc)
        assert len(entries) == 3
        assert entries[0][0] == 1
        assert entries[1][0] == 2
        assert entries[2][0] == 3

    def test_header_present(self):
        """TOC starts with '## Table of Contents' header.

        **Validates: Requirement 6.1**
        """
        toc = _generate_toc(["Section A"])
        assert toc.startswith("## Table of Contents\n")

    def test_ampersand_in_title(self):
        """Ampersand in title (e.g., 'Error Handling & Code Mapping') is removed from anchor.

        **Validates: Requirement 6.3**
        """
        toc = _generate_toc(["Error Handling & Code Mapping"])
        entries = _parse_toc_entries(toc)
        _, _, anchor = entries[0]
        assert anchor == "error-handling-code-mapping"
        assert "&" not in anchor

    def test_single_entry(self):
        """A single section produces exactly one TOC entry.

        **Validates: Requirement 6.2**
        """
        toc = _generate_toc(["Only Section"])
        entries = _parse_toc_entries(toc)
        assert len(entries) == 1
        assert entries[0] == (1, "Only Section", "only-section")
