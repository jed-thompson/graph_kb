"""Property-based tests for prompt extension correctness.

Property 9: Prompt extension correctness — For any agent context containing
            prior_sections_summary and/or scope_contract, the build_prompt
            output contains the corresponding "Already Covered" and/or
            "Scope Contract" blocks; when these keys are absent, the blocks
            shall be omitted.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

import os
import sys
from typing import Any

from hypothesis import given, settings, HealthCheck, strategies as st

# Import standalone utility modules directly, bypassing the package
# __init__.py which triggers heavy dependencies (sentence_transformers).
_utils_dir = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "graph_kb_api",
    "flows",
    "v3",
    "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from prompt_extensions import (  # noqa: E402
    build_already_covered_block,
    build_scope_contract_block,
)

sys.path.pop(0)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for non-empty summary text
summary_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=500,
).filter(lambda s: s.strip())

# Strategy for scope_includes / scope_excludes topic lists
topic_list_st = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
        min_size=1,
        max_size=80,
    ).filter(lambda s: s.strip()),
    min_size=0,
    max_size=10,
)

# Strategy for cross_cutting_owner (None or a section ID string)
cross_cutting_owner_st = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=40,
    ).filter(lambda s: s.strip()),
)

# Strategy for a scope_contract dict
scope_contract_st = st.fixed_dictionaries(
    {
        "scope_includes": topic_list_st,
        "scope_excludes": topic_list_st,
        "cross_cutting_owner": cross_cutting_owner_st,
    }
)


@st.composite
def agent_context_st(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a random agent_context with optional prior_sections_summary
    and scope_contract keys."""
    ctx: dict[str, Any] = {}

    include_summary = draw(st.booleans())
    include_scope = draw(st.booleans())

    if include_summary:
        ctx["prior_sections_summary"] = draw(summary_text_st)

    if include_scope:
        ctx["scope_contract"] = draw(scope_contract_st)

    return ctx


# ---------------------------------------------------------------------------
# Property 9: Prompt extension correctness
# ---------------------------------------------------------------------------


class TestPromptExtensionCorrectness:
    """Property 9: Prompt extension correctness.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(ctx=agent_context_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_already_covered_present_iff_summary_present(
        self, ctx: dict[str, Any]
    ):
        """When prior_sections_summary is present and non-empty, the
        Already Covered block appears; when absent, it does not.

        **Validates: Requirements 3.1, 3.3**
        """
        summary = ctx.get("prior_sections_summary")
        block = build_already_covered_block(summary or "")

        if summary and summary.strip():
            assert "## Already Covered" in block, (
                f"Expected '## Already Covered' in block for summary={summary!r}"
            )
            assert summary.strip() in block
        else:
            assert block == "", (
                f"Expected empty block when summary is absent, got: {block!r}"
            )

    @given(ctx=agent_context_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_scope_contract_present_iff_contract_present(
        self, ctx: dict[str, Any]
    ):
        """When scope_contract is present with actionable content, the
        Scope Contract block appears; when absent, it does not.

        **Validates: Requirements 3.2, 3.4**
        """
        contract = ctx.get("scope_contract")
        block = build_scope_contract_block(contract) if contract else ""

        has_includes = bool(contract and contract.get("scope_includes"))
        has_excludes = bool(contract and contract.get("scope_excludes"))

        if has_includes or has_excludes:
            assert "## Scope Contract" in block, (
                f"Expected '## Scope Contract' in block for contract={contract!r}"
            )
        else:
            assert block == "", (
                f"Expected empty block when contract has no topics, got: {block!r}"
            )

    @given(contract=scope_contract_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_scope_includes_listed_under_must_cover(
        self, contract: dict[str, Any]
    ):
        """When scope_includes is non-empty, all topics appear under
        '### Must Cover'.

        **Validates: Requirements 3.2**
        """
        block = build_scope_contract_block(contract)
        includes = contract.get("scope_includes", [])

        if includes:
            assert "### Must Cover" in block
            for topic in includes:
                assert f"- {topic}" in block, (
                    f"Topic {topic!r} not found in block"
                )

    @given(contract=scope_contract_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_scope_excludes_listed_under_must_not_cover(
        self, contract: dict[str, Any]
    ):
        """When scope_excludes is non-empty, all topics appear under
        '### Must NOT Cover'.

        **Validates: Requirements 3.2**
        """
        block = build_scope_contract_block(contract)
        excludes = contract.get("scope_excludes", [])

        if excludes:
            assert "### Must NOT Cover" in block
            for topic in excludes:
                assert f"- {topic}" in block, (
                    f"Topic {topic!r} not found in block"
                )

    @given(contract=scope_contract_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_cross_cutting_owner_referenced_when_present(
        self, contract: dict[str, Any]
    ):
        """When cross_cutting_owner is set and excludes exist, the owner
        section ID appears in the Must NOT Cover header.

        **Validates: Requirements 3.2**
        """
        block = build_scope_contract_block(contract)
        owner = contract.get("cross_cutting_owner")
        excludes = contract.get("scope_excludes", [])

        if owner and excludes:
            assert owner in block, (
                f"cross_cutting_owner {owner!r} not found in block"
            )
