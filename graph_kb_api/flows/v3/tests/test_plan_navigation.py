"""Tests for PlanEngine.navigate_to_phase backward navigation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from graph_kb_api.flows.v3.graphs.plan_engine import PlanEngine
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import CASCADE_MAP


def _make_fingerprint(phase: str, input_hash: str = "abc123") -> dict:
    """Helper to create a minimal PhaseFingerprint dict."""
    return {
        "phase": phase,
        "input_hash": input_hash,
        "output_refs": [f"{phase}/output.json"],
        "completed_at": "2025-01-01T00:00:00+00:00",
    }


@pytest.fixture
def workflow_context():
    """Create a minimal WorkflowContext for testing."""
    mock_llm = MagicMock()
    mock_llm.name = "test-llm"
    return WorkflowContext(
        llm=mock_llm,
        app_context=None,
        artifact_service=None,
        blob_storage=None,
        checkpointer=None,
    )


class TestNavigateToPhase:
    """Test PlanEngine.navigate_to_phase cascade invalidation."""

    @pytest.mark.asyncio
    async def test_clears_target_and_downstream(self, workflow_context):
        """navigate_to_phase clears completed_phases for target + downstream."""
        engine = PlanEngine(workflow_context)

        # Mock aget_state to return state with completed phases
        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "completed_phases": {
                "context": True,
                "research": True,
                "planning": True,
                "orchestrate": True,
                "assembly": True,
            },
            "fingerprints": {},
        }
        engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
        engine.workflow.aupdate_state = AsyncMock()

        result = await engine.navigate_to_phase("research", {"configurable": {"thread_id": "t1"}})

        # Target + all downstream per CASCADE_MAP["research"]
        expected_cleared = {
            "research",
            "planning",
            "orchestrate",
            "assembly",
        }
        assert set(result["cleared_phases"]) == expected_cleared

        # Verify aupdate_state was called with False for each cleared phase
        call_args = engine.workflow.aupdate_state.call_args
        updated = call_args[0][1].update["completed_phases"]
        for phase in expected_cleared:
            assert updated[phase] is False

    @pytest.mark.asyncio
    async def test_returns_dirty_phases_with_fingerprints(self, workflow_context):
        """navigate_to_phase returns dirty_phases for downstream with existing fingerprints."""
        engine = PlanEngine(workflow_context)

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "completed_phases": {"context": True, "research": True, "planning": True},
            "fingerprints": {
                "planning": _make_fingerprint("planning"),
                "orchestrate": _make_fingerprint("orchestrate"),
                # assembly has no fingerprint
            },
        }
        engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
        engine.workflow.aupdate_state = AsyncMock()

        result = await engine.navigate_to_phase("research", {"configurable": {"thread_id": "t1"}})

        # Only planning and orchestrate have fingerprints among research's downstream
        assert set(result["dirty_phases"]) == {"planning", "orchestrate"}

    @pytest.mark.asyncio
    async def test_cascade_map_used_for_downstream(self, workflow_context):
        """navigate_to_phase uses CASCADE_MAP to determine downstream phases."""
        engine = PlanEngine(workflow_context)

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "completed_phases": {},
            "fingerprints": {},
        }
        engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
        engine.workflow.aupdate_state = AsyncMock()

        # Navigate to "planning" — downstream should be orchestrate, assembly
        result = await engine.navigate_to_phase("planning", {"configurable": {"thread_id": "t1"}})

        expected = {"planning"} | set(CASCADE_MAP["planning"])
        assert set(result["cleared_phases"]) == expected

    @pytest.mark.asyncio
    async def test_navigate_to_first_phase_clears_all_downstream(self, workflow_context):
        """Navigating to 'context' clears all downstream phases."""
        engine = PlanEngine(workflow_context)

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "completed_phases": {p: True for p in CASCADE_MAP},
            "fingerprints": {p: _make_fingerprint(p) for p in CASCADE_MAP},
        }
        engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
        engine.workflow.aupdate_state = AsyncMock()

        result = await engine.navigate_to_phase("context", {"configurable": {"thread_id": "t1"}})

        # context + all its downstream
        expected = {"context"} | set(CASCADE_MAP["context"])
        assert set(result["cleared_phases"]) == expected
        # All downstream phases have fingerprints, so all are dirty
        assert set(result["dirty_phases"]) == set(CASCADE_MAP["context"])

    @pytest.mark.asyncio
    async def test_navigate_to_last_phase_clears_only_target(self, workflow_context):
        """Navigating to 'assembly' (no downstream) clears only itself."""
        engine = PlanEngine(workflow_context)

        mock_snapshot = MagicMock()
        mock_snapshot.values = {
            "completed_phases": {"assembly": True},
            "fingerprints": {},
        }
        engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
        engine.workflow.aupdate_state = AsyncMock()

        result = await engine.navigate_to_phase("assembly", {"configurable": {"thread_id": "t1"}})

        assert result["cleared_phases"] == ["assembly"]
        assert result["dirty_phases"] == []

    @pytest.mark.asyncio
    async def test_empty_state_snapshot(self, workflow_context):
        """navigate_to_phase handles None state snapshot gracefully."""
        engine = PlanEngine(workflow_context)

        engine.workflow.aget_state = AsyncMock(return_value=None)
        engine.workflow.aupdate_state = AsyncMock()

        result = await engine.navigate_to_phase("research", {"configurable": {"thread_id": "t1"}})

        # Should still clear phases even with empty state
        assert "research" in result["cleared_phases"]
        assert result["dirty_phases"] == []

    @pytest.mark.asyncio
    async def test_target_phase_always_in_cleared(self, workflow_context):
        """The target phase is always included in cleared_phases."""
        engine = PlanEngine(workflow_context)

        mock_snapshot = MagicMock()
        mock_snapshot.values = {"completed_phases": {}, "fingerprints": {}}
        engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
        engine.workflow.aupdate_state = AsyncMock()

        for phase in CASCADE_MAP:
            result = await engine.navigate_to_phase(phase, {"configurable": {"thread_id": "t1"}})
            assert result["target_phase"] == phase
            assert phase in result["cleared_phases"]
