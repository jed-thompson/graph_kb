"""Property-based tests for interrupt preservation (Pattern B nodes).

Property 8: Interrupt Preservation
For any interrupt-based node (ApprovalNode, HumanInputNode), when
``interrupt()`` is called inside ``_execute_async``, the ``NodeInterrupt``
must propagate through the base class ``__call__`` to LangGraph.

**Validates: Requirements 3.1, 17.8**
"""

from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langgraph.errors import NodeInterrupt

from graph_kb_api.flows.v3.nodes.approval_node import ApprovalNode
from graph_kb_api.flows.v3.nodes.human_input_node import HumanInputNode

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def approval_state(draw: st.DrawFn):
    """Generate a plausible state dict for ApprovalNode."""
    final_output = draw(
        st.text(
            min_size=0,
            max_size=200,
            alphabet=st.characters(
                whitelist_categories=("L", "Zs", "N"),
                whitelist_characters=".,;:-_\n#*",
            ),
        )
    )
    return {"final_output": final_output}


@st.composite
def human_input_state(draw: st.DrawFn):
    """Generate a plausible state dict for HumanInputNode."""
    num_gaps = draw(st.integers(min_value=0, max_value=5))
    gaps = {}
    questions = []
    for i in range(num_gaps):
        gap_id = f"gap_{i}"
        question = draw(
            st.text(
                min_size=1,
                max_size=80,
                alphabet=st.characters(whitelist_categories=("L", "Zs", "N")),
            )
        )
        resolved = draw(st.booleans())
        gaps[gap_id] = {"question": question, "resolved": resolved}
        questions.append(question)
    return {
        "gaps_detected": gaps,
        "clarification_questions": questions,
    }


# ---------------------------------------------------------------------------
# Property 8: Interrupt Preservation
# ---------------------------------------------------------------------------


class TestInterruptPreservation:
    """Property 8: Interrupt Preservation.

    When ``interrupt()`` is called inside ``_execute_async`` for
    ApprovalNode and HumanInputNode, ``NodeInterrupt`` propagates
    through the base class ``__call__``.

    **Validates: Requirements 3.1, 17.8**
    """

    @given(state=approval_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_approval_node_interrupt_propagates(self, state):
        """ApprovalNode: NodeInterrupt propagates through base __call__."""
        node = ApprovalNode()

        with patch(
            "graph_kb_api.flows.v3.nodes.approval_node.interrupt",
            side_effect=NodeInterrupt("approval_needed"),
        ):
            with pytest.raises(NodeInterrupt):
                await node(state)

    @given(state=human_input_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_human_input_node_interrupt_propagates(self, state):
        """HumanInputNode: NodeInterrupt propagates through base __call__."""
        node = HumanInputNode()

        with patch(
            "graph_kb_api.flows.v3.nodes.human_input_node.interrupt",
            side_effect=NodeInterrupt("clarification_needed"),
        ):
            with pytest.raises(NodeInterrupt):
                await node(state)
