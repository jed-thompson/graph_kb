"""Property-based tests for extract_section_summaries().

Property 10: Section summary extraction bound — For any set of ordered
             section keys and hydrated sections, the extracted section
             summaries truncate each section's content to
             max_chars_per_section characters and produce one entry per
             section.

**Validates: Requirement 7.1**
"""

from __future__ import annotations

import os
import sys
from typing import Any

from hypothesis import given, settings, HealthCheck, strategies as st

# Import the standalone utility directly, bypassing the package __init__.py
# which triggers heavy dependencies (sentence_transformers).
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from section_summaries import extract_section_summaries  # noqa: E402

sys.path.pop(0)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def sections_st(draw: st.DrawFn) -> tuple[list[str], dict[str, str], int]:
    """Generate random ordered keys, hydrated sections, and max_chars_per_section.

    Guarantees:
    - At least 1 section
    - All ordered_keys exist in hydrated_sections
    - Content can be empty or multi-paragraph
    - max_chars_per_section is a positive integer
    """
    num_sections = draw(st.integers(min_value=1, max_value=20))
    keys = [f"section_{i}" for i in range(num_sections)]

    hydrated: dict[str, str] = {}
    for key in keys:
        # Generate content that may contain paragraph breaks
        paragraphs = draw(st.lists(
            st.text(min_size=0, max_size=500, alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
                blacklist_characters="\x00",
            )),
            min_size=0,
            max_size=5,
        ))
        hydrated[key] = "\n\n".join(paragraphs)

    max_chars = draw(st.integers(min_value=1, max_value=1000))
    return keys, hydrated, max_chars


# ---------------------------------------------------------------------------
# Property 10: Section summary extraction bound
# ---------------------------------------------------------------------------


class TestSectionSummaryExtractionBound:
    """Property 10: Section summary extraction bound.

    **Validates: Requirement 7.1**
    """

    @given(data=sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_one_entry_per_section(
        self, data: tuple[list[str], dict[str, str], int]
    ):
        """For any set of ordered keys and hydrated sections, the output
        contains exactly one ``### {key}`` entry per section.

        **Validates: Requirement 7.1**
        """
        ordered_keys, hydrated_sections, max_chars = data
        result = extract_section_summaries(ordered_keys, hydrated_sections, max_chars)

        for key in ordered_keys:
            assert f"### {key}\n" in result, (
                f"Missing entry for section '{key}' in output"
            )

        # Count entries by looking for the exact markers we expect.
        # A naive ``result.count("### ")`` would over-count when section
        # content itself contains markdown headings.
        entry_count = sum(1 for key in ordered_keys if f"### {key}\n" in result)
        assert entry_count == len(ordered_keys), (
            f"Expected {len(ordered_keys)} entries, found {entry_count}"
        )

    @given(data=sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_each_section_truncated_to_max_chars(
        self, data: tuple[list[str], dict[str, str], int]
    ):
        """For any set of ordered keys and hydrated sections, each section's
        extracted content is at most max_chars_per_section characters.

        **Validates: Requirement 7.1**
        """
        ordered_keys, hydrated_sections, max_chars = data
        result = extract_section_summaries(ordered_keys, hydrated_sections, max_chars)

        # Parse each entry by finding "### {key}\n" markers for each known key
        for i, key in enumerate(ordered_keys):
            marker = f"### {key}\n"
            assert marker in result, f"Missing marker for section '{key}'"
            start = result.index(marker) + len(marker)
            # Find the end: either the next "### " marker at line start or end of string
            if i + 1 < len(ordered_keys):
                next_marker = f"### {ordered_keys[i + 1]}\n"
                end = result.index(next_marker)
            else:
                end = len(result)
            content = result[start:end].strip()
            assert len(content) <= max_chars, (
                f"Section '{key}' content length {len(content)} "
                f"exceeds max_chars_per_section={max_chars}"
            )
