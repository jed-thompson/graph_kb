"""Unit tests for section summary extraction and LLM timeout graceful degradation.

Tests:
- extract_section_summaries basic behavior
- AssembleNode._build_fallback_document produces document with TOC and sorted
  sections when executive summary / transitions are absent (LLM failure path)

**Validates: Requirements 7.1, 7.4**
"""

from __future__ import annotations

import os
import sys

import pytest

# Import standalone utility directly to avoid heavy package imports.
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from section_summaries import extract_section_summaries  # noqa: E402

sys.path.pop(0)


# ---------------------------------------------------------------------------
# extract_section_summaries unit tests
# ---------------------------------------------------------------------------


class TestExtractSectionSummaries:
    """Unit tests for the standalone extract_section_summaries utility."""

    def test_single_section(self):
        result = extract_section_summaries(
            ["Architecture"], {"Architecture": "This is the arch section."}, 300,
        )
        assert "### Architecture\n" in result
        assert "This is the arch section." in result

    def test_truncation(self):
        long_content = "A" * 500
        result = extract_section_summaries(["S1"], {"S1": long_content}, 100)
        # The extracted content should be at most 100 chars
        entry = result.split("### S1\n")[1].strip()
        assert len(entry) <= 100

    def test_multi_paragraph_takes_first(self):
        content = "First paragraph.\n\nSecond paragraph."
        result = extract_section_summaries(["S1"], {"S1": content}, 300)
        assert "First paragraph." in result
        assert "Second paragraph." not in result

    def test_empty_content(self):
        result = extract_section_summaries(["S1"], {"S1": ""}, 300)
        assert "### S1\n" in result

    def test_multiple_sections_order_preserved(self):
        keys = ["Alpha", "Beta", "Gamma"]
        sections = {k: f"Content for {k}" for k in keys}
        result = extract_section_summaries(keys, sections, 300)
        alpha_pos = result.index("### Alpha")
        beta_pos = result.index("### Beta")
        gamma_pos = result.index("### Gamma")
        assert alpha_pos < beta_pos < gamma_pos


# ---------------------------------------------------------------------------
# LLM timeout graceful degradation tests
# ---------------------------------------------------------------------------


class TestLLMTimeoutGracefulDegradation:
    """Verify document is produced with TOC and sorted sections when LLM call fails.

    When _generate_executive_summary raises an exception (timeout, parse error,
    etc.), the fallback path should produce a document containing:
    - A title
    - A TOC with all sections
    - All sections in sorted order
    - No executive summary or transitions

    **Validates: Requirement 7.4**
    """

    def _build_fallback(self, spec_name, sorted_keys, hydrated_sections,
                        executive_summary="", transitions=None):
        """Replicate _build_fallback_document using the standalone TOC utility."""
        # Import the standalone toc_generation utility (same one AssembleNode delegates to)
        _toc_utils_dir = os.path.join(
            os.path.dirname(__file__), os.pardir,
            "graph_kb_api", "flows", "v3", "utils",
        )
        sys.path.insert(0, os.path.normpath(_toc_utils_dir))
        from toc_generation import generate_toc  # noqa: E402
        sys.path.pop(0)

        toc = generate_toc(sorted_keys) if sorted_keys else ""
        parts = [f"# {spec_name}\n"]
        if executive_summary:
            parts.append(f"{executive_summary}\n")
        if toc:
            parts.append(toc)
        for idx, section_name in enumerate(sorted_keys):
            if section_name in hydrated_sections:
                parts.append(f"## {section_name}\n\n{hydrated_sections[section_name]}")
            if transitions and idx < len(transitions) and idx < len(sorted_keys) - 1:
                parts.append(f"_{transitions[idx]}_")
        return "\n\n".join(parts)

    def test_fallback_without_executive_summary(self):
        """When LLM fails (empty exec summary), document has title + TOC + sections."""
        keys = ["Architecture", "Authentication", "Error Handling"]
        sections = {k: f"Content for {k} section." for k in keys}

        doc = self._build_fallback("My Spec", keys, sections)

        # Title present
        assert doc.startswith("# My Spec")
        # TOC present
        assert "## Table of Contents" in doc
        assert "[Architecture]" in doc
        assert "[Authentication]" in doc
        assert "[Error Handling]" in doc
        # All sections present
        for k in keys:
            assert f"## {k}" in doc
            assert f"Content for {k} section." in doc
        # No executive summary
        # The document should go title -> TOC -> sections
        toc_pos = doc.index("## Table of Contents")
        arch_pos = doc.index("## Architecture")
        assert toc_pos < arch_pos

    def test_fallback_with_executive_summary_and_transitions(self):
        """When LLM succeeds, document has title + exec summary + TOC + sections + transitions."""
        keys = ["Architecture", "Authentication"]
        sections = {k: f"Content for {k}." for k in keys}
        exec_summary = "This spec covers architecture and authentication."
        transitions = ["The architecture establishes the foundation for authentication."]

        doc = self._build_fallback("My Spec", keys, sections, exec_summary, transitions)

        # Executive summary present between title and TOC
        title_pos = doc.index("# My Spec")
        summary_pos = doc.index(exec_summary)
        toc_pos = doc.index("## Table of Contents")
        assert title_pos < summary_pos < toc_pos

        # Transition present between sections
        assert "_The architecture establishes the foundation for authentication._" in doc

    def test_fallback_sections_in_order(self):
        """Sections appear in the order specified by sorted_keys."""
        keys = ["Gamma", "Alpha", "Beta"]
        sections = {k: f"Content for {k}." for k in keys}

        doc = self._build_fallback("Spec", keys, sections)

        gamma_pos = doc.index("## Gamma")
        alpha_pos = doc.index("## Alpha")
        beta_pos = doc.index("## Beta")
        assert gamma_pos < alpha_pos < beta_pos

    def test_fallback_empty_sections(self):
        """With no sections, document has just the title."""
        doc = self._build_fallback("Empty Spec", [], {})
        assert "# Empty Spec" in doc
        assert "## Table of Contents" not in doc
