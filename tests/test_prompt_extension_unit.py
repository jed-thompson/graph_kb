"""Unit tests for build_prompt prompt extensions (scope contract + prior summary).

Tests: context with both keys, with only prior_sections_summary,
with only scope_contract, and with neither key.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

from __future__ import annotations

import os
import sys

# Import standalone utility modules directly, bypassing the package
# __init__.py which triggers heavy dependencies.
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


class TestBuildAlreadyCoveredBlock:
    """Unit tests for build_already_covered_block.

    **Validates: Requirements 3.1, 3.3**
    """

    def test_returns_block_when_summary_present(self):
        """Non-empty summary produces an '## Already Covered' block."""
        summary = (
            '- Section "Auth" (sec_auth): OAuth2 flow, token caching.\n'
            '- Section "Address" (sec_addr): US-only validation.'
        )
        result = build_already_covered_block(summary)
        assert "## Already Covered" in result
        assert "OAuth2 flow" in result
        assert "US-only validation" in result

    def test_returns_empty_when_summary_empty(self):
        """Empty string summary produces empty block."""
        assert build_already_covered_block("") == ""

    def test_returns_empty_when_summary_whitespace(self):
        """Whitespace-only summary produces empty block."""
        assert build_already_covered_block("   \n  ") == ""

    def test_strips_surrounding_whitespace(self):
        """Summary with leading/trailing whitespace is stripped."""
        result = build_already_covered_block("  some summary  ")
        assert result == "## Already Covered\nsome summary"


class TestBuildScopeContractBlock:
    """Unit tests for build_scope_contract_block.

    **Validates: Requirements 3.2, 3.4**
    """

    def test_full_contract_with_includes_and_excludes(self):
        """Contract with both includes and excludes produces full block."""
        contract = {
            "scope_includes": ["request body construction", "field mapping"],
            "scope_excludes": ["URL encoding rules", "error code mapping"],
            "cross_cutting_owner": "spec_section_error_mapping",
        }
        result = build_scope_contract_block(contract)
        assert "## Scope Contract" in result
        assert "### Must Cover" in result
        assert "- request body construction" in result
        assert "- field mapping" in result
        assert "### Must NOT Cover" in result
        assert "- URL encoding rules" in result
        assert "- error code mapping" in result
        assert "spec_section_error_mapping" in result

    def test_contract_with_only_includes(self):
        """Contract with only includes produces Must Cover section only."""
        contract = {
            "scope_includes": ["pipeline topology"],
            "scope_excludes": [],
            "cross_cutting_owner": None,
        }
        result = build_scope_contract_block(contract)
        assert "## Scope Contract" in result
        assert "### Must Cover" in result
        assert "- pipeline topology" in result
        assert "### Must NOT Cover" not in result

    def test_contract_with_only_excludes(self):
        """Contract with only excludes produces Must NOT Cover section only."""
        contract = {
            "scope_includes": [],
            "scope_excludes": ["error code mapping"],
            "cross_cutting_owner": None,
        }
        result = build_scope_contract_block(contract)
        assert "## Scope Contract" in result
        assert "### Must Cover" not in result
        assert "### Must NOT Cover (defined elsewhere)" in result
        assert "- error code mapping" in result

    def test_contract_with_cross_cutting_owner_in_header(self):
        """When cross_cutting_owner is set, it appears in the Must NOT Cover header."""
        contract = {
            "scope_includes": [],
            "scope_excludes": ["test matrix"],
            "cross_cutting_owner": "sec_testing",
        }
        result = build_scope_contract_block(contract)
        assert "see sec_testing" in result

    def test_contract_without_cross_cutting_owner(self):
        """When cross_cutting_owner is None, header says 'defined elsewhere' only."""
        contract = {
            "scope_includes": [],
            "scope_excludes": ["test matrix"],
            "cross_cutting_owner": None,
        }
        result = build_scope_contract_block(contract)
        assert "### Must NOT Cover (defined elsewhere)" in result

    def test_empty_contract_returns_empty(self):
        """Empty contract dict produces empty block."""
        assert build_scope_contract_block({}) == ""

    def test_none_contract_returns_empty(self):
        """None contract produces empty block."""
        assert build_scope_contract_block(None) == ""

    def test_contract_with_empty_lists_returns_empty(self):
        """Contract with empty includes and excludes produces empty block."""
        contract = {
            "scope_includes": [],
            "scope_excludes": [],
            "cross_cutting_owner": None,
        }
        assert build_scope_contract_block(contract) == ""


class TestBuildPromptIntegration:
    """Integration tests verifying build_prompt includes/excludes blocks.

    Tests the combined behaviour of both extension functions to verify
    blocks appear/disappear correctly in a simulated build_prompt flow.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @staticmethod
    def _build_prompt(task: dict, agent_context: dict) -> str:
        """Simulate build_prompt's extension logic using standalone utilities.

        Builds a minimal prompt from task fields, then appends the scope
        contract and already-covered blocks exactly as build_prompt does.
        """
        parts: list[str] = []

        description = task.get("description", "")
        if description:
            parts.append(f"## Task\n{description}")

        title = task.get("title", "")
        if title:
            parts.append(f"## Section Title\n{title}")

        # Legacy fields
        kb_results = agent_context.get("kb_results")
        if kb_results:
            parts.append(f"## Codebase Context\n{kb_results}")

        # Scope contract and prior summary blocks (near end)
        scope_contract = agent_context.get("scope_contract")
        scope_block = build_scope_contract_block(scope_contract) if scope_contract else ""
        if scope_block:
            parts.append(scope_block)

        prior_summary = agent_context.get("prior_sections_summary")
        already_covered_block = build_already_covered_block(prior_summary) if prior_summary else ""
        if already_covered_block:
            parts.append(already_covered_block)

        return "\n\n".join(parts) if parts else "Generate the requested section."

    def test_both_keys_present(self):
        """Context with both prior_sections_summary and scope_contract
        produces both blocks in the prompt."""
        task = {"description": "Draft the section", "title": "Test Section"}
        ctx = {
            "prior_sections_summary": '- Section "Auth" (sec_auth): OAuth2 flow.',
            "scope_contract": {
                "scope_includes": ["request body"],
                "scope_excludes": ["error mapping"],
                "cross_cutting_owner": "sec_errors",
            },
        }
        result = self._build_prompt(task, ctx)
        assert "## Already Covered" in result
        assert "## Scope Contract" in result
        assert "### Must Cover" in result
        assert "### Must NOT Cover" in result

    def test_only_prior_summary(self):
        """Context with only prior_sections_summary produces Already Covered
        but not Scope Contract."""
        task = {"description": "Draft the section", "title": "Test Section"}
        ctx = {
            "prior_sections_summary": '- Section "Auth" (sec_auth): OAuth2 flow.',
        }
        result = self._build_prompt(task, ctx)
        assert "## Already Covered" in result
        assert "## Scope Contract" not in result

    def test_only_scope_contract(self):
        """Context with only scope_contract produces Scope Contract
        but not Already Covered."""
        task = {"description": "Draft the section", "title": "Test Section"}
        ctx = {
            "scope_contract": {
                "scope_includes": ["request body"],
                "scope_excludes": [],
                "cross_cutting_owner": None,
            },
        }
        result = self._build_prompt(task, ctx)
        assert "## Scope Contract" in result
        assert "## Already Covered" not in result

    def test_neither_key_present(self):
        """Context with neither key produces neither block."""
        task = {"description": "Draft the section", "title": "Test Section"}
        ctx = {}
        result = self._build_prompt(task, ctx)
        assert "## Already Covered" not in result
        assert "## Scope Contract" not in result

    def test_blocks_appear_near_end(self):
        """Scope Contract and Already Covered blocks appear after other
        content sections (near end of prompt for recency bias)."""
        task = {"description": "Draft the section", "title": "Test Section"}
        ctx = {
            "prior_sections_summary": "- Prior section summary.",
            "scope_contract": {
                "scope_includes": ["topic A"],
                "scope_excludes": ["topic B"],
                "cross_cutting_owner": None,
            },
            "kb_results": "Some KB context here.",
        }
        result = self._build_prompt(task, ctx)
        # The blocks should appear after the KB context
        kb_pos = result.index("## Codebase Context")
        scope_pos = result.index("## Scope Contract")
        covered_pos = result.index("## Already Covered")
        assert scope_pos > kb_pos, "Scope Contract should appear after Codebase Context"
        assert covered_pos > scope_pos, "Already Covered should appear after Scope Contract"
