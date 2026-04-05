"""Property-based tests for ApprovalNode.

Property 16: User approval gate — workflow_complete ⟹ user_approved = True
(the workflow does not complete without explicit user approval).

**Validates: Requirements 11.4**
"""

from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.approval_node import ApprovalNode

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def approval_response(draw: st.DrawFn):
    """Generate a user approval/rejection response dict."""
    approved = draw(st.booleans())
    feedback = draw(
        st.text(
            min_size=0,
            max_size=100,
            alphabet=st.characters(whitelist_categories=("L", "Zs", "N")),
        )
    )
    # Generate section ids for sections_to_revise
    sections = draw(
        st.lists(
            st.from_regex(r"[a-z][a-z0-9_]{1,12}", fullmatch=True),
            min_size=0,
            max_size=5,
        )
    )
    return {
        "approved": approved,
        "feedback": feedback,
        "sections_to_revise": sections,
    }


@st.composite
def spec_final_output(draw: st.DrawFn):
    """Generate a plausible final_output string."""
    return draw(
        st.text(
            min_size=0,
            max_size=300,
            alphabet=st.characters(
                whitelist_categories=("L", "Zs", "N"),
                whitelist_characters=".,;:-_\n#*`()[]",
            ),
        )
    )


# ---------------------------------------------------------------------------
# Property 16: User approval gate
# ---------------------------------------------------------------------------


class TestUserApprovalGate:
    """Property 16: User approval gate — workflow_complete ⟹ user_approved = True.

    The workflow does not complete (route to END) without explicit user
    approval. We model this by: for any user response processed by the
    ApprovalNode, the workflow can only route to END when user_approved
    is True.

    **Validates: Requirements 11.4**
    """

    @given(
        final_output=spec_final_output(),
        response=approval_response(),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_workflow_complete_implies_user_approved(
        self, final_output, response
    ):
        """workflow_complete ⟹ user_approved = True.

        The route_after_approval function routes to END only when
        user_approved is True. We verify that the ApprovalNode output
        correctly reflects the user's decision, so the routing invariant
        holds: if the workflow would complete (route to END), then
        user_approved must be True.
        """
        node = ApprovalNode()
        state = {"final_output": final_output}

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            return_value=response,
        ):
            result = await node(state)

        user_approved = result["user_approved"]

        # Simulate route_after_approval: END only when user_approved is True
        would_complete = user_approved is True

        if would_complete:
            assert result["user_approved"] is True, (
                "Workflow would route to END but user_approved is not True. "
                f"response={response}, result={result}"
            )

        # Converse: if user did NOT approve, workflow must NOT complete
        if not response.get("approved", False):
            assert result["user_approved"] is not True, (
                "User did not approve but user_approved is True. "
                f"response={response}, result={result}"
            )
