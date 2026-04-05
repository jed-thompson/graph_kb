"""Property-based test for session isolation.

Property 9: Session Isolation — For any two concurrent sessions with
             distinct sessionIds, operations on one session do not affect
             state or events of the other.

**Validates: Requirements 20.1, 20.2, 20.3, 20.4**
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.graphs.unified_spec_engine import (
    PHASE_ORDER,
    UnifiedSpecEngine,
)
from graph_kb_api.websocket.handlers.spec_v3_dispatcher import (
    _get_session,
    _register_session,
    _sessions,
    _validate_session_owner,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate distinct session ID pairs
_session_id_st = st.uuids().map(str)

# Generate distinct client IDs
_client_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=3,
    max_size=30,
)

# Generate workflow IDs
_workflow_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-"),
    min_size=1,
    max_size=20,
)

# Generate arbitrary phase data to simulate state mutations
_phase_data_st = st.fixed_dictionaries(
    {"marker": st.text(min_size=1, max_size=30)},
    optional={
        "extra": st.text(max_size=20),
        "approved": st.booleans(),
    },
)

# Generate a phase name
_phase_st = st.sampled_from(PHASE_ORDER)

# Generate config extra keys to simulate mutations
_config_extra_key_st = st.text(
    alphabet=st.characters(whitelist_categories=("L",)),
    min_size=1,
    max_size=10,
)

_config_extra_value_st = st.text(min_size=1, max_size=20)


@st.composite
def distinct_session_pair_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a pair of sessions with distinct IDs, clients, and configs."""
    sid1 = draw(_session_id_st)
    sid2 = draw(_session_id_st.filter(lambda s: s != sid1))
    client1 = draw(_client_id_st)
    client2 = draw(_client_id_st)
    wf1 = draw(_workflow_id_st)
    wf2 = draw(_workflow_id_st)
    return {
        "sid1": sid1,
        "sid2": sid2,
        "client1": client1,
        "client2": client2,
        "wf1": wf1,
        "wf2": wf2,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> UnifiedSpecEngine:
    """Create an engine with mocked dependencies."""
    llm = MagicMock()
    app_context = MagicMock()
    app_context.llm = llm
    app_context.graph_store = MagicMock()
    return UnifiedSpecEngine(
        llm=llm,
        app_context=app_context,
        checkpointer=None,
        mode="wizard",
    )


def _make_config(session_id: str) -> Dict[str, Any]:
    """Build a LangGraph config with a thread_id derived from session_id."""
    return {"configurable": {"thread_id": f"spec-{session_id}"}}


# ---------------------------------------------------------------------------
# Property 9: Session Isolation
# ---------------------------------------------------------------------------


class TestSessionIsolationProperty:
    """Property 9: Session Isolation — For any two concurrent sessions with
    distinct sessionIds, operations on one session (state updates, event
    routing, checkpoint writes) do not affect the state or events of the
    other session.

    **Validates: Requirements 20.1, 20.2, 20.3, 20.4**
    """

    # ── Property: distinct sessions get distinct thread_ids (Req 20.1) ──

    @given(pair=distinct_session_pair_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_distinct_sessions_get_distinct_thread_ids(
        self,
        pair: Dict[str, Any],
    ):
        """For any two sessions with distinct sessionIds, the thread_ids
        assigned in the LangGraph config are also distinct.

        **Validates: Requirements 20.1**
        """
        config1 = _make_config(pair["sid1"])
        config2 = _make_config(pair["sid2"])

        tid1 = config1["configurable"]["thread_id"]
        tid2 = config2["configurable"]["thread_id"]

        assert tid1 != tid2, (
            f"Two distinct sessions ({pair['sid1']}, {pair['sid2']}) "
            f"must have distinct thread_ids, got: {tid1}"
        )

    # ── Property: registering session B does not affect session A (Req 20.2, 20.4) ──

    @given(pair=distinct_session_pair_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_registering_second_session_does_not_affect_first(
        self,
        pair: Dict[str, Any],
    ):
        """For any two sessions registered sequentially, the first session's
        data is unchanged after the second is registered.

        **Validates: Requirements 20.2, 20.4**
        """
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()
            config1 = _make_config(pair["sid1"])
            config2 = _make_config(pair["sid2"])

            _register_session(
                pair["sid1"], engine1, config1, pair["client1"], pair["wf1"]
            )

            # Snapshot session 1 state before registering session 2
            s1_before = copy.deepcopy(_get_session(pair["sid1"]))

            _register_session(
                pair["sid2"], engine2, config2, pair["client2"], pair["wf2"]
            )

            # Session 1 must be unchanged
            s1_after = _get_session(pair["sid1"])
            assert s1_after["config"] == s1_before["config"], (
                "Registering session 2 modified session 1's config"
            )
            assert s1_after["client_id"] == s1_before["client_id"]
            assert s1_after["workflow_id"] == s1_before["workflow_id"]
        finally:
            _sessions.clear()

    # ── Property: config mutation on one session doesn't leak (Req 20.4) ──

    @given(
        pair=distinct_session_pair_st(),
        extra_key=_config_extra_key_st,
        extra_value=_config_extra_value_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_config_mutation_does_not_leak_between_sessions(
        self,
        pair: Dict[str, Any],
        extra_key: str,
        extra_value: str,
    ):
        """For any two sessions, mutating one session's config dict does
        not affect the other session's config.

        **Validates: Requirements 20.4**
        """
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()
            config1 = _make_config(pair["sid1"])
            config2 = _make_config(pair["sid2"])

            _register_session(
                pair["sid1"], engine1, config1, pair["client1"], pair["wf1"]
            )
            _register_session(
                pair["sid2"], engine2, config2, pair["client2"], pair["wf2"]
            )

            # Snapshot session 2 config
            s2_config_before = copy.deepcopy(_get_session(pair["sid2"])["config"])

            # Mutate session 1's config
            s1 = _get_session(pair["sid1"])
            s1["config"]["configurable"][extra_key] = extra_value

            # Session 2 must be unaffected
            s2 = _get_session(pair["sid2"])
            assert s2["config"] == s2_config_before, (
                f"Mutating session 1's config leaked key '{extra_key}' into session 2"
            )
        finally:
            _sessions.clear()

    # ── Property: session lookup is isolated (Req 20.2) ──

    @given(pair=distinct_session_pair_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_session_lookup_returns_only_own_data(
        self,
        pair: Dict[str, Any],
    ):
        """For any two sessions, _get_session(sid1) returns session 1's data
        and _get_session(sid2) returns session 2's data — never crossed.

        **Validates: Requirements 20.2**
        """
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()
            config1 = _make_config(pair["sid1"])
            config2 = _make_config(pair["sid2"])

            _register_session(
                pair["sid1"], engine1, config1, pair["client1"], pair["wf1"]
            )
            _register_session(
                pair["sid2"], engine2, config2, pair["client2"], pair["wf2"]
            )

            s1 = _get_session(pair["sid1"])
            s2 = _get_session(pair["sid2"])

            # Each session returns its own engine instance
            assert s1["engine"] is engine1
            assert s2["engine"] is engine2
            assert s1["engine"] is not s2["engine"]

            # Each session returns its own client_id
            assert s1["client_id"] == pair["client1"]
            assert s2["client_id"] == pair["client2"]

            # Thread IDs are distinct
            assert (
                s1["config"]["configurable"]["thread_id"]
                != s2["config"]["configurable"]["thread_id"]
            )
        finally:
            _sessions.clear()

    # ── Property: owner validation prevents cross-session access (Req 20.2, 20.3) ──

    @given(pair=distinct_session_pair_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_owner_validation_prevents_cross_session_access(
        self,
        pair: Dict[str, Any],
    ):
        """For any two sessions owned by different clients, client A cannot
        pass ownership validation for session B and vice versa.

        **Validates: Requirements 20.2, 20.3**
        """
        _sessions.clear()
        try:
            engine1 = _make_engine()
            engine2 = _make_engine()
            config1 = _make_config(pair["sid1"])
            config2 = _make_config(pair["sid2"])

            _register_session(
                pair["sid1"], engine1, config1, pair["client1"], pair["wf1"]
            )
            _register_session(
                pair["sid2"], engine2, config2, pair["client2"], pair["wf2"]
            )

            s1 = _get_session(pair["sid1"])
            s2 = _get_session(pair["sid2"])

            # Owner validates for own session
            assert _validate_session_owner(s1, pair["client1"], pair["sid1"]) is True
            assert _validate_session_owner(s2, pair["client2"], pair["sid2"]) is True

            # Cross-client access is rejected (when clients differ)
            if pair["client1"] != pair["client2"]:
                assert (
                    _validate_session_owner(s1, pair["client2"], pair["sid1"]) is False
                ), "Client 2 should not pass validation for session 1"
                assert (
                    _validate_session_owner(s2, pair["client1"], pair["sid2"]) is False
                ), "Client 1 should not pass validation for session 2"
        finally:
            _sessions.clear()

    # ── Property: initial state is independent per session (Req 20.4) ──

    @given(
        pair=distinct_session_pair_st(),
        phase_data=_phase_data_st,
        phase=_phase_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_initial_state_mutation_does_not_leak(
        self,
        pair: Dict[str, Any],
        phase_data: Dict[str, Any],
        phase: str,
    ):
        """For any two engines building initial state, mutating one engine's
        state does not affect the other's.

        **Validates: Requirements 20.4**
        """
        engine1 = _make_engine()
        engine2 = _make_engine()

        state1 = engine1._build_initial_state({"context": {"spec_name": "Feature A"}})
        state2 = engine2._build_initial_state({"context": {"spec_name": "Feature B"}})

        # Mutate state1's phase data
        state1[phase] = phase_data
        state1["completed_phases"][phase] = True

        # state2 must be unaffected
        if phase == "context":
            assert state2["context"] == {"spec_name": "Feature B"}, (
                f"Mutating state1['{phase}'] leaked into state2"
            )
        else:
            assert state2[phase] == {}, f"Mutating state1['{phase}'] leaked into state2"
        assert state2["completed_phases"][phase] is False, (
            f"Mutating state1 completed_phases['{phase}'] leaked into state2"
        )

    # ── Property: engine instances are independent (Req 20.4) ──

    @given(pair=distinct_session_pair_st())
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_engine_instances_are_independent(
        self,
        pair: Dict[str, Any],
    ):
        """For any two sessions, each gets its own engine instance with
        independent internal state.

        **Validates: Requirements 20.4**
        """
        engine1 = _make_engine()
        engine2 = _make_engine()

        # Engines are distinct objects
        assert engine1 is not engine2

        # Modifying one engine's callback doesn't affect the other
        engine1._progress_callback = lambda e: None
        assert engine2._progress_callback is None

        # Each engine has its own app_context
        assert engine1._app_context is not engine2._app_context

    # ── Property: deep-copy on registration prevents source mutation (Req 20.4) ──

    @given(
        pair=distinct_session_pair_st(),
        extra_key=_config_extra_key_st,
        extra_value=_config_extra_value_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_source_config_mutation_after_registration_is_isolated(
        self,
        pair: Dict[str, Any],
        extra_key: str,
        extra_value: str,
    ):
        """For any session, mutating the original config dict after
        registration does not affect the registered session's config.

        **Validates: Requirements 20.4**
        """
        _sessions.clear()
        try:
            engine = _make_engine()
            config = _make_config(pair["sid1"])

            _register_session(
                pair["sid1"], engine, config, pair["client1"], pair["wf1"]
            )

            # Snapshot the registered config
            registered_config = copy.deepcopy(_get_session(pair["sid1"])["config"])

            # Mutate the original config
            config["configurable"][extra_key] = extra_value

            # Registered session must be unaffected
            assert _get_session(pair["sid1"])["config"] == registered_config, (
                f"Mutating source config after registration leaked "
                f"key '{extra_key}' into session"
            )
        finally:
            _sessions.clear()
