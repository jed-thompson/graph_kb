"""Property-based tests for cascade navigation downstream clearing.

Property 17: Cascade Navigation Downstream Clearing — validates that
when navigating backward to any phase, the PlanEngine clears
``completed_phases`` flags for exactly the target phase plus all
downstream phases listed in ``CASCADE_MAP[phase]``.

**Validates: Requirement 30.1**
"""

from typing import Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.graphs.plan_engine import PlanEngine
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext
from graph_kb_api.flows.v3.state.plan_state import CASCADE_MAP


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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Draw a valid phase from CASCADE_MAP keys
_phase_st = st.sampled_from(sorted(CASCADE_MAP.keys()))

# Generate an arbitrary completed_phases dict: each CASCADE_MAP phase is
# randomly True or False (simulating partially-completed workflows).
_completed_phases_st = st.fixed_dictionaries(
    {phase: st.booleans() for phase in CASCADE_MAP}
)

# Generate an arbitrary fingerprints dict: a random subset of phases have
# fingerprint entries.
_fingerprints_st = st.fixed_dictionaries(
    {
        phase: st.one_of(
            st.none(),
            st.fixed_dictionaries(
                {
                    "phase": st.just(phase),
                    "input_hash": st.text(
                        alphabet="0123456789abcdef", min_size=64, max_size=64
                    ),
                    "output_refs": st.just([f"{phase}/output.json"]),
                    "completed_at": st.just("2025-01-01T00:00:00+00:00"),
                }
            ),
        )
        for phase in CASCADE_MAP
    }
).map(lambda d: {k: v for k, v in d.items() if v is not None})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine_with_state(
    workflow_context: WorkflowContext,
    completed_phases: Dict[str, bool],
    fingerprints: dict,
) -> PlanEngine:
    """Create a PlanEngine with mocked workflow state."""
    engine = PlanEngine(workflow_context)
    mock_snapshot = MagicMock()
    mock_snapshot.values = {
        "completed_phases": completed_phases,
        "fingerprints": fingerprints,
    }
    engine.workflow.aget_state = AsyncMock(return_value=mock_snapshot)
    engine.workflow.aupdate_state = AsyncMock()
    return engine


# ---------------------------------------------------------------------------
# Property 17.1: Cleared phases equal target ∪ CASCADE_MAP[target]
# ---------------------------------------------------------------------------


class TestClearedPhasesMatchCascadeMap:
    """For any phase in CASCADE_MAP and any completed_phases state,
    ``navigate_to_phase`` clears exactly ``{target} ∪ CASCADE_MAP[target]``.

    **Validates: Requirement 30.1**
    """

    @given(
        target=_phase_st,
        completed_phases=_completed_phases_st,
        fingerprints=_fingerprints_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @pytest.mark.asyncio
    async def test_cleared_equals_target_union_downstream(
        self,
        workflow_context,
        target: str,
        completed_phases: Dict[str, bool],
        fingerprints: dict,
    ):
        engine = _make_engine_with_state(workflow_context, completed_phases, fingerprints)
        result = await engine.navigate_to_phase(
            target, {"configurable": {"thread_id": "t1"}}
        )

        expected = {target} | set(CASCADE_MAP[target])
        assert set(result["cleared_phases"]) == expected


# ---------------------------------------------------------------------------
# Property 17.2: All cleared phases are set to False in state update
# ---------------------------------------------------------------------------


class TestClearedPhasesSetToFalse:
    """For any phase, the ``aupdate_state`` call sets every cleared phase
    to ``False`` in ``completed_phases``.

    **Validates: Requirement 30.1**
    """

    @given(
        target=_phase_st,
        completed_phases=_completed_phases_st,
        fingerprints=_fingerprints_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @pytest.mark.asyncio
    async def test_update_state_sets_false(
        self,
        workflow_context,
        target: str,
        completed_phases: Dict[str, bool],
        fingerprints: dict,
    ):
        engine = _make_engine_with_state(workflow_context, completed_phases, fingerprints)
        await engine.navigate_to_phase(target, {"configurable": {"thread_id": "t1"}})

        call_args = engine.workflow.aupdate_state.call_args
        updated = call_args[0][1].update["completed_phases"]

        expected_phases = {target} | set(CASCADE_MAP[target])
        for phase in expected_phases:
            assert updated[phase] is False, (
                f"Phase {phase!r} should be False after navigating to {target!r}"
            )


# ---------------------------------------------------------------------------
# Property 17.3: Non-downstream phases are NOT cleared
# ---------------------------------------------------------------------------


class TestNonDownstreamPhasesUntouched:
    """For any phase, phases NOT in ``{target} ∪ CASCADE_MAP[target]``
    must NOT appear in the ``aupdate_state`` cleared dict.

    **Validates: Requirement 30.1**
    """

    @given(
        target=_phase_st,
        completed_phases=_completed_phases_st,
        fingerprints=_fingerprints_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @pytest.mark.asyncio
    async def test_non_downstream_not_in_update(
        self,
        workflow_context,
        target: str,
        completed_phases: Dict[str, bool],
        fingerprints: dict,
    ):
        engine = _make_engine_with_state(workflow_context, completed_phases, fingerprints)
        await engine.navigate_to_phase(target, {"configurable": {"thread_id": "t1"}})

        call_args = engine.workflow.aupdate_state.call_args
        updated_keys = set(call_args[0][1].update["completed_phases"].keys())

        expected = {target} | set(CASCADE_MAP[target])
        unexpected = updated_keys - expected
        assert unexpected == set(), (
            f"Phases {unexpected} should not be cleared when navigating to {target!r}"
        )


# ---------------------------------------------------------------------------
# Property 17.4: Target phase is always in cleared_phases
# ---------------------------------------------------------------------------


class TestTargetAlwaysCleared:
    """For any phase, the target phase itself is always included in
    ``cleared_phases``.

    **Validates: Requirement 30.1**
    """

    @given(
        target=_phase_st,
        completed_phases=_completed_phases_st,
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
    @pytest.mark.asyncio
    async def test_target_in_cleared(
        self,
        workflow_context,
        target: str,
        completed_phases: Dict[str, bool],
    ):
        engine = _make_engine_with_state(workflow_context, completed_phases, {})
        result = await engine.navigate_to_phase(
            target, {"configurable": {"thread_id": "t1"}}
        )
        assert target in result["cleared_phases"]
