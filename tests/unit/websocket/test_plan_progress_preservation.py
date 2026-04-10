# Preservation property tests - Plan Workflow Progress
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Strategies
_config_key_st = st.text(
    min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_")
)
_config_value_st = st.one_of(
    st.text(min_size=0, max_size=50), st.integers(min_value=-1000, max_value=1000), st.booleans()
)
_client_id_st = st.text(
    min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_")
)
_session_id_st = st.text(
    min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_")
)
_event_type_st = st.sampled_from(
    ["plan.phase.progress", "plan.phase.enter", "plan.phase.complete", "plan.task.start", "plan.task.complete"]
)
_phase_st = st.sampled_from(["context", "review", "research", "plan", "orchestrate", "planning", "assembly"])
_field_st = st.fixed_dictionaries(
    {
        "id": st.text(
            min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_")
        ),
        "label": st.text(min_size=1, max_size=50),
        "type": st.sampled_from(["text", "textarea", "select"]),
        "required": st.booleans(),
    }
)
_prefilled_st = st.dictionaries(
    keys=st.text(
        min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_")
    ),
    values=st.text(min_size=0, max_size=50),
    min_size=0,
    max_size=5,
)


class TestConfigServicesPreservation:
    """Preservation: get_config_with_services auto-injects all non-None
    WorkflowContext fields, and pre-existing keys in configurable are preserved
    (unless they share a name with a non-None WorkflowContext field).

    **Validates: Requirements 3.3, 14.5**
    """

    @given(
        pre_existing=st.dictionaries(keys=_config_key_st, values=_config_value_st, min_size=0, max_size=5),
        thread_id=st.text(
            min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_")
        ),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_config_always_contains_artifact_service_and_llm(self, pre_existing, thread_id):
        """For all base configs, result always contains non-None WorkflowContext fields,
        and pre-existing keys survive (unless overridden by a non-None field).

        **Validates: Requirements 3.3, 14.5**
        """
        mock_artifact = MagicMock(name="artifact_service")
        mock_llm = MagicMock(name="llm")

        with (
            patch("graph_kb_api.flows.v3.graphs.plan_engine.PlanEngine._initialize_nodes"),
            patch("graph_kb_api.flows.v3.graphs.plan_engine.PlanEngine._compile_workflow", return_value=MagicMock()),
        ):
            from graph_kb_api.flows.v3.graphs.plan_engine import PlanEngine
            from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext

            import dataclasses

            workflow_context = WorkflowContext(
                llm=mock_llm,
                app_context=None,
                artifact_service=mock_artifact,
                blob_storage=None,
                checkpointer=MagicMock(),
            )
            engine = PlanEngine(workflow_context)

            # Collect names of non-None WorkflowContext fields (these will be injected)
            injected_field_names = {
                f.name
                for f in dataclasses.fields(workflow_context)
                if getattr(workflow_context, f.name) is not None
            }

            base_configurable = {"thread_id": thread_id}
            base_configurable.update(pre_existing)
            base_config = {"configurable": dict(base_configurable)}

            result = engine.get_config_with_services(base_config)
            configurable = result["configurable"]

            assert "artifact_service" in configurable, "artifact_service missing"
            assert configurable["artifact_service"] is mock_artifact
            assert "llm" in configurable, "llm missing"
            assert configurable["llm"] is mock_llm
            assert configurable["thread_id"] == thread_id, "thread_id overwritten"
            # Pre-existing keys survive unless they collide with an injected field
            for key, value in pre_existing.items():
                if key not in injected_field_names and key != "context":
                    assert key in configurable, f"Pre-existing key '{key}' removed"
                    assert configurable[key] == value, f"Pre-existing key '{key}' changed"


class TestEmitEventDeliveryPreservation:
    """Preservation: _emit_event with non-None client_id calls send_event
    with exact args - no data transformation.

    **Validates: Requirements 3.4**
    """

    @given(
        client_id=_client_id_st,
        event_type=_event_type_st,
        session_id=_session_id_st,
        extra_data=st.dictionaries(keys=_config_key_st, values=_config_value_st, min_size=0, max_size=3),
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_send_event_called_with_exact_args(self, client_id, event_type, session_id, extra_data):
        """For all events with non-None client_id, send_event receives exact args.

        **Validates: Requirements 3.4**
        """
        import graph_kb_api.websocket.plan_events as plan_events_module

        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(return_value=True)

        data = {"session_id": session_id, "phase": "research", "message": "test"}
        data.update(extra_data)
        data_snapshot = dict(data)

        original_manager = plan_events_module._plan_ws_manager
        try:
            plan_events_module._plan_ws_manager = mock_manager

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    plan_events_module._emit_event(
                        event_type=event_type,
                        session_id=session_id,
                        data=data,
                        client_id=client_id,
                    )
                )
            finally:
                loop.close()

            assert mock_manager.send_event.called, "send_event not called"
            call_kwargs = mock_manager.send_event.call_args.kwargs
            assert call_kwargs["client_id"] == client_id
            assert call_kwargs["event_type"] == event_type
            assert call_kwargs["workflow_id"] == session_id
            assert call_kwargs["data"] == data_snapshot, "data was transformed"
        finally:
            plan_events_module._plan_ws_manager = original_manager


class TestEmitPhasePromptFieldsPreservation:
    """Preservation: _emit_phase_prompt with fields/prefilled (no summary/options)
    produces valid SpecPhasePromptData with those values intact.

    **Validates: Requirements 3.5**
    """

    @given(
        phase=_phase_st,
        session_id=_session_id_st,
        fields=st.lists(_field_st, min_size=1, max_size=4),
        prefilled=_prefilled_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_fields_and_prefilled_preserved_in_prompt(self, phase, session_id, fields, prefilled):
        """For interrupt data with fields/prefilled (no summary/options),
        emitted payload preserves fields and prefilled values.

        **Validates: Requirements 3.5**
        """
        from graph_kb_api.websocket.handlers import plan_dispatcher

        mock_send_event = AsyncMock(return_value=True)

        interrupt_data = {
            "phase": phase,
            "session_id": session_id,
            "fields": list(fields),
            "prefilled": dict(prefilled),
        }
        fields_snapshot = list(fields)
        prefilled_snapshot = dict(prefilled)

        with patch.object(plan_dispatcher, "manager") as mock_mgr:
            mock_mgr.send_event = mock_send_event

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(plan_dispatcher._emit_phase_prompt("c1", "w1", interrupt_data))
            finally:
                loop.close()

            assert mock_send_event.called, "send_event not called"
            call_kwargs = mock_send_event.call_args.kwargs
            sent_data = call_kwargs["data"]

            assert "fields" in sent_data, "fields missing"
            sent_fields = sent_data["fields"]
            assert len(sent_fields) == len(fields_snapshot), "fields count mismatch"
            for i, (expected, actual) in enumerate(zip(fields_snapshot, sent_fields)):
                assert actual["id"] == expected["id"], f"Field {i} id mismatch"
                assert actual["label"] == expected["label"], f"Field {i} label mismatch"
                assert actual["type"] == expected["type"], f"Field {i} type mismatch"

            if prefilled_snapshot:
                assert "prefilled" in sent_data and sent_data["prefilled"] is not None, "prefilled missing"
                for key, value in prefilled_snapshot.items():
                    assert sent_data["prefilled"].get(key) == value, f"prefilled[{key!r}] mismatch"

            assert call_kwargs["event_type"] == "plan.phase.prompt"
            assert call_kwargs["client_id"] == "c1"
            assert call_kwargs["workflow_id"] == "w1"


class TestEmitEventDisconnectResilience:
    """Preservation: when send_event raises an exception, _emit_event catches
    it and does not propagate (fire-and-forget pattern).

    **Validates: Requirements 3.6**
    """

    @given(
        client_id=_client_id_st,
        event_type=_event_type_st,
        session_id=_session_id_st,
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_send_event_exception_does_not_propagate(self, client_id, event_type, session_id):
        """When send_event raises, _emit_event catches it - workflow continues.

        **Validates: Requirements 3.6**
        """
        import graph_kb_api.websocket.plan_events as plan_events_module

        mock_manager = MagicMock()
        mock_manager.send_event = AsyncMock(side_effect=ConnectionError("client disconnected"))

        original_manager = plan_events_module._plan_ws_manager
        try:
            plan_events_module._plan_ws_manager = mock_manager
            data = {"session_id": session_id, "phase": "research", "message": "test"}

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    plan_events_module._emit_event(
                        event_type=event_type,
                        session_id=session_id,
                        data=data,
                        client_id=client_id,
                    )
                )
            finally:
                loop.close()

            assert mock_manager.send_event.called, "send_event not called"
        finally:
            plan_events_module._plan_ws_manager = original_manager
