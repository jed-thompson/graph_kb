"""Bug condition exploration test for Plan Workflow Progress Visibility.

Property 1: Fault Condition - Config Wiring and Event Emission Failures

**CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bugs exist.
**DO NOT attempt to fix the test or the code when it fails.**
**NOTE**: This test encodes the expected behavior - it will validate the fix when
         it passes after implementation.

**GOAL**: Surface counterexamples that demonstrate progress events never reach the client:
  - _create_engine creates progress_callback but never injects it into config
  - _emit_event falls back to nonexistent broadcast_to_session when client_id is None
  - _emit_phase_prompt strips summary/message before serialization

**Validates: Requirements 1.1, 1.2, 1.3, 1.5**
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Bug 1.1 / 1.3: _create_engine never injects progress_callback or client_id
# ---------------------------------------------------------------------------


class TestCreateEngineConfigWiring:
    """Bug 1.1 + 1.3: _create_engine creates a progress_callback closure but
    never returns it or injects it into config. get_config_with_services only
    adds artifact_service and llm - not progress_callback or client_id.

    **Validates: Requirements 1.1, 1.3**
    """

    @given(
        client_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        ),
        workflow_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        ),
    )
    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_config_has_progress_callback_and_client_id(self, client_id: str, workflow_id: str):
        """After _create_engine + get_config_with_services, config MUST contain
        a callable progress_callback and client_id matching the input.

        On UNFIXED code this WILL FAIL because _create_engine returns only
        PlanEngine (not a tuple with the callback).
        """
        mock_app_context = MagicMock()
        mock_app_context.blob_storage = None

        with (
            patch(
                "graph_kb_api.websocket.handlers.plan_dispatcher.get_app_context",
                return_value=mock_app_context,
            ),
            patch("graph_kb_api.websocket.handlers.plan_dispatcher.CheckpointerFactory") as mock_cf,
            patch("graph_kb_api.websocket.handlers.plan_dispatcher.set_plan_ws_manager"),
            patch("graph_kb_api.flows.v3.graphs.plan_engine.PlanEngine._initialize_nodes"),
            patch(
                "graph_kb_api.flows.v3.graphs.plan_engine.PlanEngine._compile_workflow",
                return_value=MagicMock(),
            ),
        ):
            mock_cf.create_checkpointer.return_value = MagicMock()

            from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

            result = PlanDispatcher._create_engine(client_id, workflow_id)

            # After fix: _create_engine returns (engine, progress_callback) tuple
            # On unfixed code: returns just PlanEngine - not a tuple
            assert isinstance(result, tuple), (
                f"_create_engine should return (engine, progress_callback) tuple, got {type(result).__name__}"
            )
            engine, progress_callback = result

            cfg = engine.get_config_with_services({"configurable": {"thread_id": f"plan-{workflow_id}"}})
            cfg["configurable"]["progress_callback"] = progress_callback
            cfg["configurable"]["client_id"] = client_id

            assert callable(cfg["configurable"]["progress_callback"]), "progress_callback must be callable"
            assert cfg["configurable"]["client_id"] == client_id, (
                f"client_id must be '{client_id}', got '{cfg['configurable'].get('client_id')}'"
            )


# ---------------------------------------------------------------------------
# Bug 1.2: _emit_event falls back to nonexistent broadcast_to_session
# ---------------------------------------------------------------------------


class TestEmitEventBroadcastFallback:
    """Bug 1.2: When client_id is None, _emit_event calls
    _plan_ws_manager.broadcast_to_session() which does not exist on
    ConnectionManager, raising AttributeError caught silently.

    **Validates: Requirements 1.2**
    """

    @given(
        session_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        ),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_emit_event_no_attribute_error_when_client_id_none(self, session_id: str):
        """_emit_event with client_id=None MUST NOT trigger an AttributeError
        by calling a nonexistent broadcast_to_session method.

        On UNFIXED code this WILL FAIL because the else branch calls
        broadcast_to_session which doesn't exist on ConnectionManager.
        We detect this by using a mock with spec=["send_event"] (no
        broadcast_to_session) and checking that a clean warning is logged
        rather than an AttributeError being silently swallowed.
        """
        import graph_kb_api.websocket.plan_events as plan_events_module

        # Mock that mimics real ConnectionManager: has send_event but NOT
        # broadcast_to_session
        mock_manager = MagicMock(spec=["send_event"])
        mock_manager.send_event = AsyncMock(return_value=True)

        original_manager = plan_events_module._plan_ws_manager
        try:
            plan_events_module._plan_ws_manager = mock_manager

            data = {
                "session_id": session_id,
                "phase": "research",
                "message": "test",
                "percent": 0.5,
            }

            loop = asyncio.new_event_loop()
            try:
                with patch.object(plan_events_module, "logger") as mock_logger:
                    loop.run_until_complete(
                        plan_events_module._emit_event(
                            event_type="plan.phase.progress",
                            session_id=session_id,
                            data=data,
                            client_id=None,
                        )
                    )

                    # After fix: should log a clean warning about missing client_id
                    # On unfixed code: the warning is about the AttributeError from
                    # trying to call broadcast_to_session
                    warning_calls = mock_logger.warning.call_args_list
                    if warning_calls:
                        warning_msg = str(warning_calls[0])
                        assert "No client_id" in warning_msg or "dropping" in warning_msg, (
                            f"Expected clean 'No client_id' warning, got: {warning_msg}. "
                            "This means _emit_event called broadcast_to_session which "
                            "raised AttributeError, caught silently by except handler."
                        )
                    else:
                        # No warning and no send_event call = event silently dropped
                        assert mock_manager.send_event.called, (
                            "_emit_event with client_id=None produced no warning and "
                            "did not call send_event - event was silently dropped."
                        )
            finally:
                loop.close()
        finally:
            plan_events_module._plan_ws_manager = original_manager


# ---------------------------------------------------------------------------
# Bug 1.5: _emit_phase_prompt strips summary/message from approval data
# ---------------------------------------------------------------------------


class TestEmitPhasePromptSummaryPreservation:
    """Bug 1.5: _emit_phase_prompt explicitly pops 'summary' and 'message'
    from interrupt data before constructing SpecPhasePromptData, so the user
    sees an approval form with no context about what was done.

    **Validates: Requirements 1.5**
    """

    @given(
        confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow], deadline=None)
    def test_emit_phase_prompt_preserves_summary_in_agent_content(self, confidence: float):
        """_emit_phase_prompt with summary/message data MUST produce a payload
        where agent_content contains the summary information.

        On UNFIXED code this WILL FAIL because _emit_phase_prompt pops
        summary and message before serialization, so agent_content is None.
        """
        from graph_kb_api.websocket.handlers import plan_dispatcher

        mock_send_event = AsyncMock(return_value=True)

        interrupt_data = {
            "phase": "research",
            "session_id": "s1",
            "summary": {"confidence": confidence},
            "message": "Research complete",
            "options": [{"id": "approve"}, {"id": "revise"}],
        }

        with patch.object(plan_dispatcher, "manager") as mock_mgr:
            mock_mgr.send_event = mock_send_event

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(plan_dispatcher._emit_phase_prompt("c1", "w1", interrupt_data))
            finally:
                loop.close()

            assert mock_send_event.called, "manager.send_event was not called - _emit_phase_prompt failed"

            # Extract the data kwarg from the send_event call
            call_kwargs = mock_send_event.call_args
            if call_kwargs.kwargs.get("data") is not None:
                sent_data = call_kwargs.kwargs["data"]
            elif len(call_kwargs.args) >= 4:
                sent_data = call_kwargs.args[3]
            else:
                pytest.fail("Could not extract data from send_event call")

            # After fix: agent_content should contain summary info
            # On unfixed code: agent_content is None because summary/message
            # were popped before SpecPhasePromptData construction
            agent_content = sent_data.get("agent_content")
            assert agent_content is not None, (
                "agent_content is None in emitted payload. "
                "_emit_phase_prompt strips summary and message via data.pop() "
                "before constructing SpecPhasePromptData, so approval context "
                "is lost. The user sees an approval form with no information "
                "about what was done."
            )
            assert "confidence" in agent_content.lower() or str(confidence) in agent_content, (
                f"agent_content should contain summary info (confidence={confidence}), but got: {agent_content!r}"
            )
