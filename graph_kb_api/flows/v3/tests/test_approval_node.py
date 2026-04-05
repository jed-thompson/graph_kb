"""
Unit tests for ApprovalNode.

Tests:
- Approval sets user_approved=True
- Rejection captures sections_to_revise and approval_feedback
- Boolean shortcut response
- String shortcut response (treated as rejection with feedback)

Requirements traced: 11.2, 11.3
"""

from unittest.mock import patch

import pytest

from graph_kb_api.flows.v3.nodes.approval_node import ApprovalNode


@pytest.fixture
def node():
    return ApprovalNode()


def _make_state(final_output="# Feature Spec\n\nContent here."):
    return {
        "final_output": final_output,
    }


class TestApprovalNodeApproval:
    """Tests for the approval (happy) path."""

    @pytest.mark.asyncio
    async def test_approval_sets_user_approved_true(self, node):
        """When user approves, user_approved should be True."""
        state = _make_state()
        user_response = {
            "approved": True,
            "feedback": "",
            "sections_to_revise": [],
        }

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=user_response,
        ):
            result = await node(state)

        assert result["user_approved"] is True
        assert result["approval_feedback"] == ""
        assert result["sections_to_revise"] == []

    @pytest.mark.asyncio
    async def test_approval_with_boolean_shortcut(self, node):
        """A simple True boolean response should approve."""
        state = _make_state()

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=True,
        ):
            result = await node(state)

        assert result["user_approved"] is True
        assert result["approval_feedback"] == ""
        assert result["sections_to_revise"] == []

    @pytest.mark.asyncio
    async def test_interrupt_receives_final_output(self, node):
        """The interrupt payload should contain the final_output from state."""
        spec_content = "# My Spec\n\n## Architecture\n\nDetails."
        state = _make_state(final_output=spec_content)

        captured_payload = {}

        def mock_interrupt(payload):
            captured_payload.update(payload)
            return {"approved": True, "feedback": "", "sections_to_revise": []}

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            side_effect=mock_interrupt,
        ):
            await node(state)

        assert captured_payload["type"] == "approval_needed"
        assert captured_payload["final_output"] == spec_content


class TestApprovalNodeRejection:
    """Tests for the rejection path."""

    @pytest.mark.asyncio
    async def test_rejection_captures_sections_to_revise(self, node):
        """When user rejects, sections_to_revise should be captured."""
        state = _make_state()
        user_response = {
            "approved": False,
            "feedback": "API section needs rate limiting details",
            "sections_to_revise": ["api_endpoints", "security"],
        }

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=user_response,
        ):
            result = await node(state)

        assert result["user_approved"] is False
        assert result["approval_feedback"] == "API section needs rate limiting details"
        assert result["sections_to_revise"] == ["api_endpoints", "security"]

    @pytest.mark.asyncio
    async def test_rejection_with_boolean_shortcut(self, node):
        """A simple False boolean response should reject."""
        state = _make_state()

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=False,
        ):
            result = await node(state)

        assert result["user_approved"] is False

    @pytest.mark.asyncio
    async def test_rejection_with_string_feedback(self, node):
        """A string response should be treated as rejection with feedback."""
        state = _make_state()
        feedback = "Please add more detail to the data models section"

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=feedback,
        ):
            result = await node(state)

        assert result["user_approved"] is False
        assert result["approval_feedback"] == feedback
        assert result["sections_to_revise"] == []

    @pytest.mark.asyncio
    async def test_rejection_with_empty_feedback(self, node):
        """Rejection with no feedback should still set user_approved=False."""
        state = _make_state()
        user_response = {
            "approved": False,
            "feedback": "",
            "sections_to_revise": [],
        }

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=user_response,
        ):
            result = await node(state)

        assert result["user_approved"] is False
        assert result["approval_feedback"] == ""
        assert result["sections_to_revise"] == []


class TestApprovalNodeEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_empty_final_output(self, node):
        """Node should handle empty final_output gracefully."""
        state = _make_state(final_output="")

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value={"approved": True, "feedback": "", "sections_to_revise": []},
        ):
            result = await node(state)

        assert result["user_approved"] is True

    @pytest.mark.asyncio
    async def test_missing_final_output_key(self, node):
        """Node should handle missing final_output key gracefully."""
        state = {}

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value={
                "approved": False,
                "feedback": "fix it",
                "sections_to_revise": ["arch"],
            },
        ):
            result = await node(state)

        assert result["user_approved"] is False
        assert result["sections_to_revise"] == ["arch"]

    @pytest.mark.asyncio
    async def test_node_name(self, node):
        """Node should have correct node_name."""
        assert node.node_name == "approval"
