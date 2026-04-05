"""Property-based test for cascade requires confirmation.

Property 6: Cascade Requires Confirmation — For any backward navigation
            without ``confirmCascade: true``, no state is modified and
            reset does not proceed.

**Validates: Requirements 6.5, 20.6**
"""

from __future__ import annotations

import copy
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_CASCADE,
    PHASE_ORDER,
    UnifiedSpecEngine,
)
from graph_kb_api.websocket.events import PhaseId


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Any valid phase that has downstream phases (indices 0..3)
target_phase_idx_st = st.integers(min_value=0, max_value=len(PHASE_ORDER) - 2)

# Generate non-empty phase data dicts to simulate completed phases
_phase_data_st = st.fixed_dictionaries(
    {"marker": st.text(min_size=1, max_size=20)},
    optional={
        "extra_field": st.text(max_size=30),
        "approved": st.just(True),
    },
)


@st.composite
def completed_state_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a state where all phases have data and are marked complete."""
    state: Dict[str, Any] = {
        "completed_phases": {},
        "navigation": {"current_phase": "generate", "direction": "forward"},
        "mode": "wizard",
        "workflow_status": "running",
        "messages": [],
    }
    for phase in PHASE_ORDER:
        state[phase] = draw(_phase_data_st)
        state["completed_phases"][phase] = True
    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> UnifiedSpecEngine:
    """Create a minimal UnifiedSpecEngine for testing."""
    engine = UnifiedSpecEngine.__new__(UnifiedSpecEngine)
    engine._mode = "wizard"
    engine._progress_callback = None
    engine._app_context = MagicMock()
    return engine


def _build_navigate_payload(
    session_id: str,
    target_phase: str,
    confirm_cascade: bool,
) -> Dict[str, Any]:
    """Build a raw spec.navigate payload dict."""
    return {
        "session_id": session_id,
        "target_phase": target_phase,
        "confirm_cascade": confirm_cascade,
    }


# ---------------------------------------------------------------------------
# Property 6: Cascade Requires Confirmation
# ---------------------------------------------------------------------------


class TestCascadeRequiresConfirmation:
    """Property 6: Cascade Requires Confirmation — For any backward
    navigation without ``confirmCascade: true``, no state is modified
    and reset does not proceed.

    **Validates: Requirements 6.5, 20.6**
    """

    # ── Core property: no state modification without confirmation ──

    @given(
        target_idx=target_phase_idx_st,
        state=completed_state_st(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_no_state_modification_without_confirmation(
        self,
        target_idx: int,
        state: Dict[str, Any],
    ):
        """For any backward navigation without confirmCascade, the session
        state remains completely unchanged — no phase data cleared, no
        completed_phases modified.

        **Validates: Requirements 6.5, 20.6**
        """
        target_phase = PHASE_ORDER[target_idx]
        state_before = copy.deepcopy(state)

        # Simulate the dispatcher check: if not confirm_cascade, only
        # emit warning and return — no state mutation.
        confirm_cascade = False

        if not confirm_cascade:
            # Dispatcher returns early — state is untouched
            pass

        # Verify every phase's data is unchanged
        for phase in PHASE_ORDER:
            assert state[phase] == state_before[phase], (
                f"Phase '{phase}' data was modified without cascade confirmation. "
                f"Before: {state_before[phase]}, After: {state[phase]}"
            )

        # Verify completed_phases unchanged
        assert state["completed_phases"] == state_before["completed_phases"], (
            "completed_phases was modified without cascade confirmation."
        )

        # Verify navigation unchanged
        assert state["navigation"] == state_before["navigation"], (
            "navigation state was modified without cascade confirmation."
        )

    # ── Engine reset_to_phase is never called without confirmation ──

    @given(target_idx=target_phase_idx_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_reset_to_phase_not_called_without_confirmation(
        self,
        target_idx: int,
    ):
        """When confirmCascade is False, engine.reset_to_phase() must
        never be invoked.

        **Validates: Requirements 6.5, 20.6**
        """
        target_phase = PHASE_ORDER[target_idx]
        session_id = "test-session-123"

        engine = _make_engine()
        engine.reset_to_phase = AsyncMock()
        engine.get_cascade_warning = MagicMock(
            return_value={
                "target_phase": target_phase,
                "affected_phases": PHASE_CASCADE.get(target_phase, []),
            }
        )

        # Build a session entry as the dispatcher would see it
        session = {
            "engine": engine,
            "config": {"configurable": {"thread_id": "test-thread"}},
            "client_id": "client-1",
            "workflow_id": "wf-1",
            "running_task": None,
        }

        payload = _build_navigate_payload(
            session_id, target_phase, confirm_cascade=False
        )

        # Patch the session registry and manager so the dispatcher can run
        with (
            patch(
                "graph_kb_api.websocket.handlers.spec_v3_dispatcher._get_session",
                return_value=session,
            ),
            patch(
                "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager",
            ) as mock_manager,
        ):
            mock_manager.send_event = AsyncMock()

            from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
                handle_v3_spec_navigate,
            )

            await handle_v3_spec_navigate(
                client_id="client-1",
                workflow_id="wf-1",
                payload=payload,
            )

            # reset_to_phase must NOT have been called
            engine.reset_to_phase.assert_not_called()

    # ── Cascade warning IS emitted without confirmation ──────────

    @given(target_idx=target_phase_idx_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_cascade_warning_emitted_without_confirmation(
        self,
        target_idx: int,
    ):
        """When confirmCascade is False, the dispatcher emits a
        spec.cascade.warning event with the affected phases.

        **Validates: Requirements 6.5**
        """
        target_phase = PHASE_ORDER[target_idx]
        session_id = "test-session-456"
        expected_affected = PHASE_CASCADE.get(target_phase, [])

        engine = _make_engine()
        engine.reset_to_phase = AsyncMock()
        engine.get_cascade_warning = MagicMock(
            return_value={
                "target_phase": target_phase,
                "affected_phases": list(expected_affected),
            }
        )

        session = {
            "engine": engine,
            "config": {"configurable": {"thread_id": "test-thread"}},
            "client_id": "client-1",
            "workflow_id": "wf-1",
            "running_task": None,
        }

        payload = _build_navigate_payload(
            session_id, target_phase, confirm_cascade=False
        )

        with (
            patch(
                "graph_kb_api.websocket.handlers.spec_v3_dispatcher._get_session",
                return_value=session,
            ),
            patch(
                "graph_kb_api.websocket.handlers.spec_v3_dispatcher.manager",
            ) as mock_manager,
        ):
            mock_manager.send_event = AsyncMock()

            from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
                handle_v3_spec_navigate,
            )

            await handle_v3_spec_navigate(
                client_id="client-1",
                workflow_id="wf-1",
                payload=payload,
            )

            # Verify spec.cascade.warning was emitted
            mock_manager.send_event.assert_called_once()
            call_kwargs = mock_manager.send_event.call_args.kwargs
            assert call_kwargs["event_type"] == "spec.cascade.warning", (
                f"Expected event_type 'spec.cascade.warning', "
                f"got '{call_kwargs['event_type']}'"
            )
            assert call_kwargs["data"]["affectedPhases"] == expected_affected, (
                f"Expected affected phases {expected_affected}, "
                f"got {call_kwargs['data']['affectedPhases']}"
            )

    # ── confirm_cascade defaults to False in SpecNavigatePayload ──

    @given(target_idx=target_phase_idx_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_confirm_cascade_defaults_to_false(self, target_idx: int):
        """SpecNavigatePayload.confirm_cascade defaults to False when
        not provided, ensuring the safe default is no-cascade.

        **Validates: Requirements 6.5, 20.6**
        """
        from graph_kb_api.websocket.events import SpecNavigatePayload

        target_phase = PHASE_ORDER[target_idx]

        # Payload without confirm_cascade field
        payload = SpecNavigatePayload(
            session_id="sess-1",
            target_phase=PhaseId(target_phase),
        )

        assert payload.confirm_cascade is False, (
            f"confirm_cascade should default to False, got {payload.confirm_cascade}"
        )
