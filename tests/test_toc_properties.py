"""Property-based tests for _generate_toc().

Property 5: TOC-section bijection — For any list of ordered section keys,
            the generated TOC has exactly len(ordered_keys) entries, each
            with a correctly formatted lowercase-hyphenated anchor link.

**Validates: Requirements 6.1, 6.2, 6.3, 6.4**
"""

from __future__ import annotations

import re
import sys
import os

from hypothesis import given, settings, HealthCheck, strategies as st

# Import the standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies.
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from toc_generation import generate_toc as _generate_toc  # noqa: E402

sys.path.pop(0)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Section keys: realistic section titles — letters, digits, spaces, dots,
# hyphens, and common punctuation (but not markdown-breaking chars like [ ] )
section_key_st = st.from_regex(
    r"[A-Za-z][A-Za-z0-9 .\-&:!@#$%]{0,60}",
    fullmatch=True,
)

ordered_keys_st = st.lists(section_key_st, min_size=1, max_size=30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOC_ENTRY_RE = re.compile(r"^(\d+)\.\s+\[(.+?)\]\(#(.*?)\)$")


def _parse_toc_entries(toc: str) -> list[tuple[int, str, str]]:
    """Parse TOC string into list of (number, display_text, anchor)."""
    entries: list[tuple[int, str, str]] = []
    for line in toc.splitlines():
        m = _TOC_ENTRY_RE.match(line)
        if m:
            entries.append((int(m.group(1)), m.group(2), m.group(3)))
    return entries


# ---------------------------------------------------------------------------
# Property 5: TOC-section bijection
# ---------------------------------------------------------------------------


class TestTocSectionBijection:
    """Property 5: TOC-section bijection.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    """

    @given(keys=ordered_keys_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_toc_entry_count_equals_input_length(self, keys: list[str]):
        """The number of TOC entries equals len(ordered_keys).

        **Validates: Requirements 6.2, 6.4**
        """
        toc = _generate_toc(keys)
        entries = _parse_toc_entries(toc)
        assert len(entries) == len(keys), (
            f"Expected {len(keys)} TOC entries, got {len(entries)}. "
            f"Keys: {keys}"
        )

    @given(keys=ordered_keys_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_toc_entries_are_numbered_sequentially(self, keys: list[str]):
        """TOC entries are numbered 1..N sequentially.

        **Validates: Requirements 6.1**
        """
        toc = _generate_toc(keys)
        entries = _parse_toc_entries(toc)
        for idx, (num, _, _) in enumerate(entries):
            assert num == idx + 1, (
                f"Entry {idx} has number {num}, expected {idx + 1}"
            )

    @given(keys=ordered_keys_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_toc_display_text_matches_input_keys(self, keys: list[str]):
        """Each TOC entry's display text matches the corresponding input key.

        **Validates: Requirements 6.2**
        """
        toc = _generate_toc(keys)
        entries = _parse_toc_entries(toc)
        for i, (_, display, _) in enumerate(entries):
            assert display == keys[i], (
                f"Entry {i}: display text '{display}' != key '{keys[i]}'"
            )

    @given(keys=ordered_keys_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_toc_anchors_are_lowercase_hyphenated(self, keys: list[str]):
        """Each anchor is lowercase, uses hyphens for spaces, no special chars.

        **Validates: Requirements 6.3**
        """
        toc = _generate_toc(keys)
        entries = _parse_toc_entries(toc)
        for _, _, anchor in entries:
            # Anchor should be lowercase
            assert anchor == anchor.lower(), (
                f"Anchor '{anchor}' is not lowercase"
            )
            # Anchor should not contain spaces
            assert " " not in anchor, (
                f"Anchor '{anchor}' contains spaces"
            )
            # Anchor should only contain [a-z0-9-]
            assert re.fullmatch(r"[a-z0-9-]*", anchor), (
                f"Anchor '{anchor}' contains invalid characters"
            )

    @given(keys=ordered_keys_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_toc_starts_with_header(self, keys: list[str]):
        """TOC starts with '## Table of Contents' header.

        **Validates: Requirements 6.1**
        """
        toc = _generate_toc(keys)
        assert toc.startswith("## Table of Contents\n"), (
            f"TOC does not start with expected header: {toc[:50]}"
        )
