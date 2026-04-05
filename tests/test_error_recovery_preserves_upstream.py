"""Property-based test for error recovery preserving upstream state.

Property 22: Error Recovery Preserves Upstream State — For any phase that
             fails, error is caught and ``spec.error`` emitted; retrying
             the failed phase does not re-execute or modify completed
             upstream phase data.

**Validates: Requirements 19.1, 19.2**
"""

from __future__ import annotations

import copy
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langgraph.graph import END

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    UnifiedSpecEngine,
    route_after_phase,
)
from graph_kb_api.flows.v3.nodes.spec_phases import (
    _make_error,
    generate_phase,
    plan_phase,
    research_phase,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Phase indices that can fail (review=1, research=2, plan=3, orchestrate=4,
# completeness=5, generate=6)
# Context (0) doesn't call LLM helpers so it doesn't have the try/except pattern
_failable_phase_idx_st = st.integers(min_value=1, max_value=len(PHASE_ORDER) - 1)

# Generate non-empty phase data to simulate completed upstream phases
_phase_data_st = st.fixed_dictionaries(
    {"marker": st.text(min_size=1, max_size=30)},
    optional={
        "extra": st.text(max_size=20),
        "approved": st.just(True),
    },
)

# Generate error messages
_error_message_st = st.text(min_size=1, max_size=100)

# Generate error exception types
_error_type_st = st.sampled_from(
    [RuntimeError, ConnectionError, TimeoutError, ValueError]
)


@st.composite
def upstream_completed_state_st(
    draw: st.DrawFn, failed_phase_idx: int
) -> Dict[str, Any]:
    """Generate a state where all phases upstream of the failed phase are
    complete with non-empty data.
    """
    state: Dict[str, Any] = {
        "completed_phases": {},
        "navigation": {
            "current_phase": PHASE_ORDER[failed_phase_idx],
            "direction": "forward",
        },
        "mode": "wizard",
        "workflow_status": "running",
        "messages": [],
    }

    # All upstream phases are complete with data
    for i, phase in enumerate(PHASE_ORDER):
        if i < failed_phase_idx:
            state[phase] = draw(_phase_data_st)
            state["completed_phases"][phase] = True
        else:
            state[phase] = {}
            state["completed_phases"][phase] = False

    # Ensure preconditions for each failable phase
    if failed_phase_idx >= 1:
        # review needs context complete
        state["context"].setdefault("spec_name", "Test Feature")
        state["context"].setdefault("user_explanation", "Building a test feature")
    if failed_phase_idx >= 2:
        # research needs review.approved
        state["review"]["approved"] = True
    if failed_phase_idx >= 3:
        # plan needs research.approved
        state["research"]["approved"] = True
        state["research"].setdefault("findings", {"summary": "ok"})
    if failed_phase_idx >= 4:
        # orchestrate needs plan.approved
        state["plan"]["approved"] = True
        state["plan"].setdefault("roadmap", {"phases": ["p1"]})
        state["plan"].setdefault("tasks", [{"id": "t1", "title": "Task 1"}])
    if failed_phase_idx >= 5:
        # completeness needs orchestrate.all_complete
        state["orchestrate"]["all_complete"] = True
        state["orchestrate"].setdefault(
            "task_results", [{"task_id": "t1", "status": "approved"}]
        )
    if failed_phase_idx >= 6:
        # generate needs all upstream complete + orchestrate results
        for p in PHASE_ORDER[:6]:
            state["completed_phases"][p] = True

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map phase index to (phase_function, run_helper_path)
# Index corresponds to PHASE_ORDER: 0=context, 1=review, 2=research,
# 3=plan, 4=orchestrate, 5=completeness, 6=generate
_PHASE_FUNCTIONS = {
    1: (review_phase, "graph_kb_api.flows.v3.nodes.spec_phases.ReviewerCriticAgent"),
    2: (research_phase, "graph_kb_api.flows.v3.nodes.spec_phases.run_research"),
    3: (plan_phase, "graph_kb_api.flows.v3.nodes.spec_phases.run_plan"),
    4: (orchestrate_phase, "graph_kb_api.flows.v3.nodes.spec_phases._execute_task"),
    5: (
        completeness_phase,
        "graph_kb_api.flows.v3.nodes.spec_phases._run_completeness_review",
    ),
    6: (generate_phase, "graph_kb_api.flows.v3.nodes.spec_phases.run_generate"),
}


def _make_engine() -> UnifiedSpecEngine:
    """Create a minimal UnifiedSpecEngine for testing retry logic."""
    engine = UnifiedSpecEngine.__new__(UnifiedSpecEngine)
    engine._mode = "wizard"
    engine._progress_callback = None
    engine._app_context = MagicMock()
    engine.compiled_workflow = MagicMock()
    return engine


# ---------------------------------------------------------------------------
# Property 22: Error Recovery Preserves Upstream State
# ---------------------------------------------------------------------------


class TestErrorRecoveryPreservesUpstreamState:
    """Property 22: Error Recovery Preserves Upstream State — For any phase
    that fails, error is caught and ``spec.error`` emitted; retrying the
    failed phase does not re-execute or modify completed upstream phase data.

    **Validates: Requirements 19.1, 19.2**
    """

    # ── Core property: phase failure sets error without modifying upstream ──

    @given(
        failed_idx=_failable_phase_idx_st,
        error_msg=_error_message_st,
        error_type=_error_type_st,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_phase_failure_preserves_upstream_data(
        self,
        failed_idx: int,
        error_msg: str,
        error_type: type,
        data: st.DataObject,
    ):
        """When a phase fails, the error dict is set correctly and all
        upstream phase data remains identical to its pre-failure state.

        **Validates: Requirements 19.1, 19.2**
        """
        state = data.draw(upstream_completed_state_st(failed_idx))
        failed_phase = PHASE_ORDER[failed_idx]
        upstream_phases = PHASE_ORDER[:failed_idx]

        # Snapshot upstream data before the failure
        upstream_snapshot = {
            phase: copy.deepcopy(state[phase]) for phase in upstream_phases
        }
        upstream_completed_snapshot = {
            phase: state["completed_phases"][phase] for phase in upstream_phases
        }

        # Get the phase function and its helper path
        phase_fn, helper_path = _PHASE_FUNCTIONS[failed_idx]

        # Mock the LLM helper to raise an exception
        app_context = MagicMock()
        app_context.llm = MagicMock()
        app_context.graph_store = MagicMock()

        with patch(helper_path, side_effect=error_type(error_msg)):
            if failed_idx == 1:
                # research_phase takes (state, app_context)
                result = await phase_fn(state, app_context)
            else:
                result = await phase_fn(state, app_context)

        # Verify error is set correctly (Req 19.1)
        assert "error" in result, "Phase failure should set state.error"
        assert result["error"]["phase"] == failed_phase
        assert error_msg in result["error"]["message"]
        assert result["workflow_status"] == "error"

        # Verify upstream data is NOT in the result (phase functions only
        # return updates for their own phase, not upstream phases)
        for phase in upstream_phases:
            assert phase not in result, (
                f"Phase failure result should not contain upstream phase '{phase}' data"
            )

        # Verify original state upstream data is untouched
        for phase in upstream_phases:
            assert state[phase] == upstream_snapshot[phase], (
                f"Upstream phase '{phase}' data was modified during "
                f"'{failed_phase}' failure. "
                f"Before: {upstream_snapshot[phase]}, After: {state[phase]}"
            )
            assert (
                state["completed_phases"][phase] == upstream_completed_snapshot[phase]
            ), (
                f"Upstream completed_phases['{phase}'] was modified during "
                f"'{failed_phase}' failure."
            )

    # ── Property: error state halts routing (no downstream execution) ──

    @given(
        failed_idx=_failable_phase_idx_st,
        error_msg=_error_message_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_error_state_halts_routing(
        self,
        failed_idx: int,
        error_msg: str,
    ):
        """When workflow_status is 'error', route_after_phase returns END,
        preventing any downstream phase from executing.

        **Validates: Requirements 19.1**
        """
        failed_phase = PHASE_ORDER[failed_idx]
        state = {
            "workflow_status": "error",
            "navigation": {
                "current_phase": failed_phase,
                "direction": "forward",
            },
            "error": _make_error(failed_phase, RuntimeError(error_msg)),
        }

        assert route_after_phase(state) == END, (
            f"route_after_phase should return END when workflow_status='error' "
            f"at phase '{failed_phase}'"
        )

    # ── Property: retry_phase targets only the failed phase ──

    @given(
        failed_idx=_failable_phase_idx_st,
        error_msg=_error_message_st,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_retry_targets_only_failed_phase(
        self,
        failed_idx: int,
        error_msg: str,
        data: st.DataObject,
    ):
        """retry_phase uses update_state with as_node=failed_phase and
        ainvoke(None), ensuring only the failed phase re-executes.
        Upstream phase data in the checkpoint remains untouched.

        **Validates: Requirements 19.1, 19.2**
        """
        state = data.draw(upstream_completed_state_st(failed_idx))
        failed_phase = PHASE_ORDER[failed_idx]
        upstream_phases = PHASE_ORDER[:failed_idx]

        # Snapshot upstream data
        upstream_snapshot = {
            phase: copy.deepcopy(state[phase]) for phase in upstream_phases
        }

        # Set up the engine with error state in the checkpoint
        engine = _make_engine()
        checkpoint_state = copy.deepcopy(state)
        checkpoint_state["error"] = {
            "phase": failed_phase,
            "message": error_msg,
            "code": "PHASE_EXECUTION_ERROR",
        }
        checkpoint_state["workflow_status"] = "error"

        engine.get_workflow_state = MagicMock(return_value=checkpoint_state)
        engine.compiled_workflow.update_state = MagicMock()

        # ainvoke returns a result with the retried phase data
        retry_result = copy.deepcopy(state)
        retry_result[failed_phase] = {"retried": True}
        retry_result["workflow_status"] = "running"
        retry_result["error"] = {}
        engine.compiled_workflow.ainvoke = AsyncMock(return_value=retry_result)

        config = {"configurable": {"thread_id": "test-retry"}}
        result = await engine.retry_phase(config)

        # Verify update_state was called with as_node=failed_phase
        engine.compiled_workflow.update_state.assert_called_once_with(
            config,
            {"error": {}, "workflow_status": "running"},
            as_node=failed_phase,
        )

        # Verify ainvoke was called with None (re-enter from checkpoint)
        engine.compiled_workflow.ainvoke.assert_called_once_with(None, config=config)

        # Verify upstream data in the checkpoint was not modified
        for phase in upstream_phases:
            assert checkpoint_state[phase] == upstream_snapshot[phase], (
                f"Checkpoint upstream phase '{phase}' data was modified during "
                f"retry of '{failed_phase}'."
            )

    # ── Property: full error+retry cycle preserves upstream state ──

    @given(
        failed_idx=_failable_phase_idx_st,
        error_msg=_error_message_st,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_full_error_retry_cycle_preserves_upstream(
        self,
        failed_idx: int,
        error_msg: str,
        data: st.DataObject,
    ):
        """End-to-end: a phase fails, error is set, then retry_phase is
        called. Throughout this cycle, all completed upstream phase data
        and completion flags remain unchanged.

        **Validates: Requirements 19.1, 19.2**
        """
        state = data.draw(upstream_completed_state_st(failed_idx))
        failed_phase = PHASE_ORDER[failed_idx]
        upstream_phases = PHASE_ORDER[:failed_idx]

        # Deep snapshot of upstream data before anything happens
        upstream_snapshot = {
            phase: copy.deepcopy(state[phase]) for phase in upstream_phases
        }
        upstream_completed_snapshot = {
            phase: state["completed_phases"][phase] for phase in upstream_phases
        }

        # Step 1: Simulate phase failure
        phase_fn, helper_path = _PHASE_FUNCTIONS[failed_idx]
        app_context = MagicMock()
        app_context.llm = MagicMock()
        app_context.graph_store = MagicMock()

        with patch(helper_path, side_effect=RuntimeError(error_msg)):
            error_result = await phase_fn(state, app_context)

        # Verify error was caught
        assert error_result["workflow_status"] == "error"
        assert error_result["error"]["phase"] == failed_phase

        # Step 2: Simulate retry via engine
        engine = _make_engine()
        checkpoint_state = copy.deepcopy(state)
        checkpoint_state["error"] = error_result["error"]
        checkpoint_state["workflow_status"] = "error"

        engine.get_workflow_state = MagicMock(return_value=checkpoint_state)
        engine.compiled_workflow.update_state = MagicMock()

        # Simulate successful retry result
        success_result = copy.deepcopy(state)
        success_result[failed_phase] = {"retried_successfully": True}
        success_result["workflow_status"] = "running"
        success_result["error"] = {}
        engine.compiled_workflow.ainvoke = AsyncMock(return_value=success_result)

        config = {"configurable": {"thread_id": "test-cycle"}}
        await engine.retry_phase(config)

        # Verify: upstream data unchanged throughout the entire cycle
        for phase in upstream_phases:
            assert state[phase] == upstream_snapshot[phase], (
                f"Original state upstream phase '{phase}' was modified "
                f"during error+retry cycle of '{failed_phase}'."
            )
            assert (
                state["completed_phases"][phase] == upstream_completed_snapshot[phase]
            ), (
                f"Original completed_phases['{phase}'] was modified "
                f"during error+retry cycle of '{failed_phase}'."
            )
            assert checkpoint_state[phase] == upstream_snapshot[phase], (
                f"Checkpoint upstream phase '{phase}' was modified "
                f"during retry of '{failed_phase}'."
            )
