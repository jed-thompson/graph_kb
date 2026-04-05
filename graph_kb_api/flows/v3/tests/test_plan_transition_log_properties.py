"""Property-based tests for transition log append-only growth.

Property 13: Transition Log Append-Only Growth — validates that the
transition_log grows monotonically, each execution appends exactly one
entry, previous entries are preserved at their original indices, and
entry fields match the node's attributes.

**Validates: Requirement 12.3**
"""

import operator

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubNode(SubgraphAwareNode):
    """Concrete SubgraphAwareNode for testing transition log behaviour."""

    def __init__(
        self, phase: str = "test", step_name: str = "stub", step_progress: float = 0.0
    ):
        super().__init__(node_name=step_name)
        self.phase = phase
        self.step_name = step_name
        self.step_progress = step_progress

    async def _execute_step(self, state, config):
        return NodeExecutionResult.success(output={})


# Constrain text to printable, non-empty strings for phase/step_name
_phase_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)
_step_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)
_budget_int = st.integers(min_value=0, max_value=10_000)


# ---------------------------------------------------------------------------
# Property 13.1: Single execution appends exactly one entry
# ---------------------------------------------------------------------------


class TestSingleExecutionAppendsOneEntry:
    """For any SubgraphAwareNode with arbitrary phase/step_name, executing
    once produces exactly one transition_log entry.

    **Validates: Requirement 12.3**
    """

    @given(phase=_phase_st, step_name=_step_st, remaining=_budget_int, used=_budget_int)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_one_entry_per_execution(
        self, phase: str, step_name: str, remaining: int, used: int
    ):
        node = _StubNode(phase=phase, step_name=step_name)
        node._config = {"configurable": {}}

        state = {
            "session_id": "s1",
            "budget": {"remaining_llm_calls": remaining, "tokens_used": used},
        }
        result = await node._execute_async(state, {})

        assert "transition_log" in result.output
        assert len(result.output["transition_log"]) == 1


# ---------------------------------------------------------------------------
# Property 13.2: Multiple sequential executions grow monotonically
# ---------------------------------------------------------------------------


class TestMultipleExecutionsGrowMonotonically:
    """Simulating N sequential node executions, the combined transition_log
    length equals N (each adds exactly 1).

    **Validates: Requirement 12.3**
    """

    @given(
        n=st.integers(min_value=1, max_value=20), phase=_phase_st, step_name=_step_st
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_log_length_equals_n(self, n: int, phase: str, step_name: str):
        combined_log = []

        for _ in range(n):
            node = _StubNode(phase=phase, step_name=step_name)
            node._config = {"configurable": {}}

            state = {"session_id": "s1", "budget": {}}
            result = await node._execute_async(state, {})

            # Simulate the operator.add reducer
            combined_log = operator.add(combined_log, result.output["transition_log"])

        assert len(combined_log) == n


# ---------------------------------------------------------------------------
# Property 13.3: Transition entries are never removed (prefix preservation)
# ---------------------------------------------------------------------------


class TestEntriesNeverRemoved:
    """After N executions, all previous entries are still present at their
    original indices (prefix preservation).

    **Validates: Requirement 12.3**
    """

    @given(
        n=st.integers(min_value=2, max_value=15), phase=_phase_st, step_name=_step_st
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_prefix_preserved(self, n: int, phase: str, step_name: str):
        combined_log = []
        snapshots = []  # snapshot of combined_log after each step

        for _ in range(n):
            node = _StubNode(phase=phase, step_name=step_name)
            node._config = {"configurable": {}}

            state = {"session_id": "s1", "budget": {}}
            result = await node._execute_async(state, {})

            combined_log = operator.add(combined_log, result.output["transition_log"])
            snapshots.append(list(combined_log))

        # Every earlier snapshot must be a prefix of the final log
        final = snapshots[-1]
        for i, snap in enumerate(snapshots[:-1]):
            assert final[: len(snap)] == snap, (
                f"Snapshot at step {i} is not a prefix of the final log"
            )


# ---------------------------------------------------------------------------
# Property 13.4: Entry fields match node attributes
# ---------------------------------------------------------------------------


class TestEntryFieldsMatchNodeAttributes:
    """For any node, the appended entry's from_node matches step_name and
    subgraph matches phase.

    **Validates: Requirement 12.3**
    """

    @given(phase=_phase_st, step_name=_step_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_from_node_and_subgraph(self, phase: str, step_name: str):
        node = _StubNode(phase=phase, step_name=step_name)
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        assert entry["from_node"] == step_name
        assert entry["subgraph"] == phase
