"""Tests for transition log recording in SubgraphAwareNode.

Validates Requirements 12.1, 12.2, 12.3:
- TransitionEntry appended after each node execution
- TransitionEntry has all required fields
- Budget snapshot captures current budget state
- transition_log is a list with exactly one entry per node execution
"""

from datetime import datetime

import pytest

from graph_kb_api.flows.v3.models.node_models import (
    NodeExecutionResult,
)
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode


class StubNode(SubgraphAwareNode):
    """Concrete node for testing transition log recording."""

    def __init__(self, phase="test_phase", step_name="test_step", step_progress=0.5):
        super().__init__(node_name=step_name)
        self.phase = phase
        self.step_name = step_name
        self.step_progress = step_progress

    async def _execute_step(self, state, config):
        return NodeExecutionResult.success(output={"done": True})


class StubNodeNoOutput(SubgraphAwareNode):
    """Node that returns None output to test transition_log injection."""

    def __init__(self):
        super().__init__(node_name="no_output")
        self.phase = "context"
        self.step_name = "no_output"
        self.step_progress = 0.0

    async def _execute_step(self, state, config):
        return NodeExecutionResult.success(output=None)


class TestTransitionLogAppended:
    """Test that SubgraphAwareNode appends a TransitionEntry after execution."""

    @pytest.mark.asyncio
    async def test_transition_entry_appended(self):
        node = StubNode(
            phase="research", step_name="dispatch_research", step_progress=0.3
        )
        node._config = {"configurable": {}}

        state = {
            "session_id": "s1",
            "budget": {"remaining_llm_calls": 100, "tokens_used": 500},
        }
        result = await node._execute_async(state, {})

        assert "transition_log" in result.output
        assert len(result.output["transition_log"]) == 1

    @pytest.mark.asyncio
    async def test_transition_entry_appended_when_output_is_none(self):
        node = StubNodeNoOutput()
        node._config = {"configurable": {}}

        state = {"session_id": "s1"}
        result = await node._execute_async(state, {})

        assert result.output is not None
        assert "transition_log" in result.output
        assert len(result.output["transition_log"]) == 1


class TestTransitionEntryFields:
    """Test that TransitionEntry has all required fields per Requirement 12.1."""

    @pytest.mark.asyncio
    async def test_all_required_fields_present(self):
        node = StubNode(phase="orchestrate", step_name="worker", step_progress=0.6)
        node._config = {"configurable": {}}

        state = {
            "session_id": "s1",
            "budget": {"remaining_llm_calls": 50, "tokens_used": 1200},
        }
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        assert "timestamp" in entry
        assert "from_node" in entry
        assert "to_node" in entry
        assert "subgraph" in entry
        assert "reason" in entry
        assert "budget_snapshot" in entry

    @pytest.mark.asyncio
    async def test_from_node_matches_step_name(self):
        node = StubNode(phase="planning", step_name="roadmap", step_progress=0.1)
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        assert entry["from_node"] == "roadmap"

    @pytest.mark.asyncio
    async def test_subgraph_matches_phase(self):
        node = StubNode(phase="assembly", step_name="generate", step_progress=0.4)
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        assert entry["subgraph"] == "assembly"

    @pytest.mark.asyncio
    async def test_to_node_is_next(self):
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        assert entry["to_node"] == "next"

    @pytest.mark.asyncio
    async def test_reason_is_step_complete(self):
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        assert entry["reason"] == "step_complete"

    @pytest.mark.asyncio
    async def test_timestamp_is_valid_iso(self):
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        entry = result.output["transition_log"][0]
        # Should parse without error
        parsed = datetime.fromisoformat(entry["timestamp"])
        assert parsed is not None


class TestBudgetSnapshot:
    """Test that budget_snapshot captures current budget state per Requirement 12.2."""

    @pytest.mark.asyncio
    async def test_budget_snapshot_captures_values(self):
        node = StubNode(phase="orchestrate", step_name="worker")
        node._config = {"configurable": {}}

        state = {
            "session_id": "s1",
            "budget": {"remaining_llm_calls": 42, "tokens_used": 9999},
        }
        result = await node._execute_async(state, {})

        snapshot = result.output["transition_log"][0]["budget_snapshot"]
        assert snapshot["remaining_llm_calls"] == 42
        assert snapshot["tokens_used"] == 9999

    @pytest.mark.asyncio
    async def test_budget_snapshot_defaults_when_no_budget(self):
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1"}
        result = await node._execute_async(state, {})

        snapshot = result.output["transition_log"][0]["budget_snapshot"]
        assert snapshot["remaining_llm_calls"] == 0
        assert snapshot["tokens_used"] == 0

    @pytest.mark.asyncio
    async def test_budget_snapshot_defaults_when_budget_empty(self):
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        snapshot = result.output["transition_log"][0]["budget_snapshot"]
        assert snapshot["remaining_llm_calls"] == 0
        assert snapshot["tokens_used"] == 0


class TestTransitionLogListBehavior:
    """Test that transition_log is a list with exactly one entry per execution."""

    @pytest.mark.asyncio
    async def test_exactly_one_entry_per_execution(self):
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        assert isinstance(result.output["transition_log"], list)
        assert len(result.output["transition_log"]) == 1

    @pytest.mark.asyncio
    async def test_preserves_existing_output_keys(self):
        """Transition log should not clobber other output keys from _execute_step."""
        node = StubNode()
        node._config = {"configurable": {}}

        state = {"session_id": "s1", "budget": {}}
        result = await node._execute_async(state, {})

        assert result.output["done"] is True
        assert "transition_log" in result.output
