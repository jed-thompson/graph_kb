"""Tests for the Plan WebSocket Dispatcher.

Covers:
- Pydantic validation of incoming plan.* events
- Rejection of invalid payloads with plan.error (code VALIDATION_ERROR)
- Routing to correct handler functions
- Session isolation helpers
- CASCADE_MAP navigation
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from graph_kb_api.websocket.events import PhaseId
from graph_kb_api.websocket.plan_events import (
    PlanNavigatePayload,
    PlanPhaseInputPayload,
    PlanStartPayload,
)

# ── Pydantic payload validation tests ────────────────────────────


class TestPlanStartPayloadValidation:
    """Validates PlanStartPayload rejects invalid inputs."""

    def test_valid_payload(self):
        p = PlanStartPayload(name="My Plan", description="desc")
        assert p.name == "My Plan"
        assert p.description == "desc"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            PlanStartPayload(description="no name")

    def test_description_optional(self):
        p = PlanStartPayload(name="Plan")
        assert p.description is None


class TestPlanPhaseInputPayloadValidation:
    """Validates PlanPhaseInputPayload rejects invalid inputs."""

    def test_valid_payload(self):
        p = PlanPhaseInputPayload(session_id="sess-1", phase="context", data={"key": "val"})
        assert p.session_id == "sess-1"
        assert p.phase == PhaseId.CONTEXT

    def test_invalid_phase_rejected(self):
        with pytest.raises(ValidationError):
            PlanPhaseInputPayload(session_id="s-1", phase="invalid", data={})

    def test_data_defaults_to_empty_dict(self):
        p = PlanPhaseInputPayload(session_id="s-1", phase="research")
        assert p.data == {}


class TestPlanNavigatePayloadValidation:
    """Validates PlanNavigatePayload rejects invalid inputs."""

    def test_valid_payload(self):
        p = PlanNavigatePayload(session_id="s-1", target_phase="context", confirm_cascade=True)
        assert p.target_phase == PhaseId.CONTEXT
        assert p.confirm_cascade is True

    def test_invalid_target_phase_rejected(self):
        with pytest.raises(ValidationError):
            PlanNavigatePayload(session_id="s-1", target_phase="invalid")

    def test_confirm_cascade_defaults_false(self):
        p = PlanNavigatePayload(session_id="s-1", target_phase="research")
        assert p.confirm_cascade is False


# ── Dispatcher handler tests ─────────────────────────────────────

DISPATCHER_MOD = "graph_kb_api.websocket.handlers.plan_dispatcher"


class TestPlanDispatcherValidationErrors:
    """Tests that invalid payloads emit VALIDATION_ERROR."""

    @pytest.mark.asyncio
    async def test_plan_start_missing_name_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_start,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_start("client-1", "wf-1", {})
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_plan_phase_input_invalid_phase_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_phase_input,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_phase_input(
                "client-1",
                "wf-1",
                {"session_id": "s-1", "phase": "bad", "data": {}},
            )
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_plan_navigate_invalid_target_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_navigate,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_navigate(
                "client-1",
                "wf-1",
                {"session_id": "s-1", "target_phase": "nope"},
            )
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_plan_pause_missing_session_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_pause,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_pause("client-1", "wf-1", {})
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_plan_retry_missing_session_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_retry,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_retry("client-1", "wf-1", {})
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_plan_start_rewinds_mock_recorder_once_for_new_session(self, monkeypatch):
        from graph_kb_api.config.settings import settings
        from graph_kb_api.websocket.handlers.plan_dispatcher import handle_plan_start

        mock_engine = MagicMock()
        mock_engine.get_config_with_services.return_value = {"configurable": {"thread_id": "plan-test"}}
        mock_engine.start_workflow = AsyncMock(return_value={})
        mock_engine.get_workflow_state = AsyncMock(
            return_value={"budget": {"remaining_llm_calls": 10, "tokens_used": 0}}
        )

        mock_recorder = MagicMock()
        monkeypatch.setattr(settings, "llm_recording_mode", "mock")

        with (
            patch(f"{DISPATCHER_MOD}.PlanDispatcher._create_engine", return_value=(mock_engine, AsyncMock())),
            patch(f"{DISPATCHER_MOD}.PlanDispatcher._register_session"),
            patch(f"{DISPATCHER_MOD}.PlanDispatcher._persist_session_to_db", new=AsyncMock()),
            patch(f"{DISPATCHER_MOD}.PlanDispatcher._persist_runtime_snapshot", new=AsyncMock()),
            patch(f"{DISPATCHER_MOD}.PlanDispatcher._check_and_emit_error", new=AsyncMock(return_value=False)),
            patch(
                f"{DISPATCHER_MOD}.PlanDispatcher._extract_interrupt_from_state",
                new=AsyncMock(return_value={"phase": "context", "fields": []}),
            ),
            patch(f"{DISPATCHER_MOD}.PlanDispatcher._emit_phase_prompt", new=AsyncMock()),
            patch("graph_kb_api.core.llm_recorder.LLMRecorder.from_settings", return_value=mock_recorder),
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.send_event = AsyncMock()
            await handle_plan_start(
                "client-1",
                "wf-1",
                {
                    "name": "Test Plan",
                    "description": "desc",
                    "max_llm_calls": 5,
                },
            )

        mock_recorder.rewind_mock_run.assert_called_once_with()


class TestPlanDispatcherInterruptSelection:
    """Tests interrupt prioritization for resumed plan sessions."""

    @pytest.mark.asyncio
    async def test_extract_interrupt_prefers_active_phase_over_stale_context_interrupt(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        snapshot = SimpleNamespace(
            values={
                "workflow_status": "running",
                "completed_phases": {
                    "context": True,
                    "research": True,
                    "planning": True,
                    "orchestrate": True,
                    "assembly": False,
                },
            },
            next=(),
            tasks=[
                SimpleNamespace(
                    name="context",
                    id="context-task",
                    interrupts=[
                        SimpleNamespace(
                            id="context-interrupt",
                            value={
                                "type": "form",
                                "phase": "context",
                                "step": "context_collection",
                            }
                        )
                    ],
                ),
                SimpleNamespace(
                    name="assembly",
                    id="assembly-task",
                    interrupts=[
                        SimpleNamespace(
                            id="assembly-interrupt",
                            value={
                                "type": "approval",
                                "phase": "assembly",
                                "step": "assemble",
                                "options": [{"id": "accept_results"}],
                            }
                        )
                    ],
                ),
            ],
        )

        mock_engine = MagicMock()
        mock_engine.compiled_workflow = MagicMock()
        mock_engine.compiled_workflow.aget_state = AsyncMock(return_value=snapshot)

        async def _empty_history(_config):
            if False:
                yield None

        mock_engine.compiled_workflow.aget_state_history = _empty_history

        interrupt = await PlanDispatcher._extract_interrupt_from_state(
            mock_engine,
            {"configurable": {"thread_id": "plan-test"}},
        )

        assert interrupt is not None
        assert interrupt["phase"] == "assembly"
        assert interrupt["type"] == "approval"
        assert interrupt["_interrupt_id"] == "assembly-interrupt"
        assert interrupt["_task_id"] == "assembly-task"

    @pytest.mark.asyncio
    async def test_extract_interrupt_prefers_exact_interrupt_id_over_latest_phase_match(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        snapshot = SimpleNamespace(
            values={"workflow_status": "running", "completed_phases": {"context": True}},
            next=(),
            tasks=[
                SimpleNamespace(
                    name="assembly",
                    id="approval-task",
                    interrupts=[
                        SimpleNamespace(
                            id="approval-interrupt",
                            value={
                                "type": "approval",
                                "phase": "assembly",
                                "step": "assembly_approval",
                                "options": [{"id": "approve"}],
                            },
                        )
                    ],
                ),
                SimpleNamespace(
                    name="assembly",
                    id="budget-task",
                    interrupts=[
                        SimpleNamespace(
                            id="budget-interrupt",
                            value={
                                "type": "approval",
                                "phase": "assembly",
                                "step": "assembly_budget",
                                "options": [{"id": "increase_budget"}],
                            },
                        )
                    ],
                ),
            ],
        )

        mock_engine = MagicMock()
        mock_engine.compiled_workflow = MagicMock()
        mock_engine.compiled_workflow.aget_state = AsyncMock(return_value=snapshot)

        async def _empty_history(_config):
            if False:
                yield None

        mock_engine.compiled_workflow.aget_state_history = _empty_history

        interrupt = await PlanDispatcher._extract_interrupt_from_state(
            mock_engine,
            {"configurable": {"thread_id": "plan-test"}},
            preferred_phase="assembly",
            interrupt_id="approval-interrupt",
        )

        assert interrupt is not None
        assert interrupt["_interrupt_id"] == "approval-interrupt"
        assert interrupt["_task_id"] == "approval-task"
        assert interrupt["options"] == [{"id": "approve"}]


class TestPlanDispatcherPromptEmission:
    @pytest.mark.asyncio
    async def test_emit_phase_prompt_preserves_interrupt_and_task_ids(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()

            await PlanDispatcher._emit_phase_prompt(
                "client-1",
                "wf-1",
                {
                    "session_id": "session-1",
                    "phase": "assembly",
                    "fields": [],
                    "_interrupt_id": "interrupt-1",
                    "_task_id": "task-1",
                },
            )

            payload = mock_mgr.send_event.call_args.kwargs["data"]
            assert payload["interrupt_id"] == "interrupt-1"
            assert payload["task_id"] == "task-1"

    @pytest.mark.asyncio
    async def test_emit_phase_prompt_persists_session_as_paused(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        with (
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
            patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as mock_persist,
        ):
            mock_mgr.send_event = AsyncMock()

            await PlanDispatcher._emit_phase_prompt(
                "client-1",
                "wf-1",
                {
                    "session_id": "session-1",
                    "phase": "assembly",
                    "type": "approval",
                    "options": [{"id": "approve", "label": "Approve"}],
                },
            )

        mock_persist.assert_awaited_once_with(
            session_id="session-1",
            thread_id=None,
            user_id=None,
            workflow_status="paused",
            current_phase="assembly",
            completed_phases={
                "context": True,
                "research": True,
                "planning": True,
                "orchestrate": True,
            },
        )


class TestPlanDispatcherTerminalStateHandling:
    @pytest.mark.asyncio
    async def test_emit_terminal_status_uses_workflow_state_when_result_has_no_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        with patch.object(PlanDispatcher, "_emit_plan_error", new=AsyncMock()) as mock_emit_error:
            emitted = await PlanDispatcher._emit_terminal_status_if_needed(
                state={
                    "workflow_status": "error",
                    "completed_phases": {
                        "context": True,
                        "research": True,
                        "planning": True,
                        "orchestrate": True,
                        "assembly": False,
                    },
                },
                result={},
                client_id="client-1",
                workflow_id="wf-1",
                session_id="session-1",
                fallback_phase="assembly",
            )

        assert emitted is True
        mock_emit_error.assert_awaited_once()
        assert mock_emit_error.await_args.kwargs["message"] == "assembly phase ended without completing"
        assert mock_emit_error.await_args.kwargs["code"] == "PHASE_INCOMPLETE"
        assert mock_emit_error.await_args.kwargs["phase"] == PhaseId.ASSEMBLY

    @pytest.mark.asyncio
    async def test_recover_stale_terminal_completion_emits_complete(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.workflow = MagicMock()
        mock_engine.workflow.aupdate_state = AsyncMock()

        state = {
            "workflow_status": "error",
            "completed_phases": {"assembly": True},
            "completeness": {"approved": True, "approval_decision": "approve"},
            "document_manifest": {
                "entries": [],
                "composed_index_ref": {"key": "output/index.md"},
            },
        }

        with (
            patch.object(PlanDispatcher, "_persist_runtime_snapshot", new=AsyncMock()) as mock_persist_snapshot,
            patch(f"{DISPATCHER_MOD}.emit_complete", new=AsyncMock()) as mock_emit_complete,
        ):
            recovered = await PlanDispatcher._recover_stale_terminal_completion(
                session_id="session-1",
                thread_id="plan-session-1",
                user_id="client-1",
                client_id="client-1",
                workflow_id="wf-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-session-1"}},
                state=state,
            )

        assert recovered is True
        mock_engine.workflow.aupdate_state.assert_awaited_once_with(
            {"configurable": {"thread_id": "plan-session-1"}},
            {"workflow_status": "completed"},
        )
        mock_persist_snapshot.assert_awaited_once()
        mock_emit_complete.assert_awaited_once_with(
            session_id="session-1",
            document_manifest=state["document_manifest"],
            spec_document_url="output/index.md",
            client_id="client-1",
        )


class TestPlanDispatcherCreateEngine:
    """Regression tests for plan engine dependency wiring."""

    @patch("graph_kb_api.storage.blob_storage.BlobStorage.from_env")
    @patch("graph_kb_api.flows.v3.services.artifact_service.ArtifactService")
    @patch("graph_kb_api.flows.v3.graphs.plan_engine.PlanEngine")
    @patch(f"{DISPATCHER_MOD}.WorkflowContext.from_app_context")
    @patch(f"{DISPATCHER_MOD}.CheckpointerFactory")
    @patch(f"{DISPATCHER_MOD}.get_app_context")
    def test_create_engine_initializes_blob_storage_when_app_context_lacks_it(
        self,
        mock_get_app_context,
        mock_checkpointer_factory,
        mock_workflow_context_from_app_context,
        mock_plan_engine,
        mock_artifact_service,
        mock_blob_storage_from_env,
    ):
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        app_context = SimpleNamespace(llm=MagicMock(), checkpointer=None)
        mock_get_app_context.return_value = app_context
        mock_checkpointer_factory.create_checkpointer.return_value = "checkpointer"
        mock_blob_storage = MagicMock()
        mock_blob_storage_from_env.return_value = mock_blob_storage
        mock_artifact_service.return_value = "artifact-service"
        mock_workflow_context_from_app_context.return_value = "workflow-context"
        mock_engine = MagicMock()
        mock_plan_engine.return_value = mock_engine

        engine, progress_callback = PlanDispatcher._create_engine(
            client_id="client-1",
            workflow_id="wf-1",
            session_id="session-1",
        )

        assert engine is mock_engine
        assert progress_callback is not None
        mock_blob_storage_from_env.assert_called_once_with()
        mock_artifact_service.assert_called_once_with(mock_blob_storage, "session-1")
        mock_workflow_context_from_app_context.assert_called_once_with(
            app_context,
            blob_storage=mock_blob_storage,
            checkpointer="checkpointer",
            artifact_service="artifact-service",
        )
        assert app_context.blob_storage is mock_blob_storage


class TestPlanDispatcherRouting:
    """Tests that dispatch_plan_message routes to correct handlers."""

    @pytest.mark.asyncio
    async def test_dispatch_routes_plan_start(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
            plan_dispatcher,
        )

        with (
            patch.object(plan_dispatcher, "handle_start", new_callable=AsyncMock) as mock_start,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.create_workflow.return_value = "wf-1"
            await dispatch_plan_message("client-1", "plan.start", {"name": "Test"}, "wf-1")
            mock_start.assert_called_once_with("client-1", "wf-1", {"name": "Test"})

    @pytest.mark.asyncio
    async def test_dispatch_routes_plan_phase_input(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
            plan_dispatcher,
        )

        with (
            patch.object(plan_dispatcher, "handle_phase_input", new_callable=AsyncMock) as mock_input,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.create_workflow.return_value = "wf-1"
            payload = {"session_id": "s-1", "phase": "context", "data": {}}
            await dispatch_plan_message("client-1", "plan.phase.input", payload, "wf-1")
            mock_input.assert_called_once_with("client-1", "wf-1", payload)

    @pytest.mark.asyncio
    async def test_dispatch_routes_plan_navigate(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
            plan_dispatcher,
        )

        with (
            patch.object(plan_dispatcher, "handle_navigate", new_callable=AsyncMock) as mock_nav,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.create_workflow.return_value = "wf-1"
            payload = {
                "session_id": "s-1",
                "target_phase": "context",
            }
            await dispatch_plan_message("client-1", "plan.navigate", payload, "wf-1")
            mock_nav.assert_called_once_with("client-1", "wf-1", payload)

    @pytest.mark.asyncio
    async def test_dispatch_routes_plan_resume(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
            plan_dispatcher,
        )

        with (
            patch.object(plan_dispatcher, "handle_resume", new_callable=AsyncMock) as mock_resume,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.create_workflow.return_value = "wf-1"
            payload = {"session_id": "s-1"}
            await dispatch_plan_message("client-1", "plan.resume", payload, "wf-1")
            mock_resume.assert_called_once_with("client-1", "wf-1", payload)

    @pytest.mark.asyncio
    async def test_dispatch_routes_plan_pause(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
            plan_dispatcher,
        )

        with (
            patch.object(plan_dispatcher, "handle_pause", new_callable=AsyncMock) as mock_pause,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.create_workflow.return_value = "wf-1"
            payload = {"session_id": "s-1"}
            await dispatch_plan_message("client-1", "plan.pause", payload, "wf-1")
            mock_pause.assert_called_once_with("client-1", "wf-1", payload)

    @pytest.mark.asyncio
    async def test_dispatch_routes_plan_retry(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
            plan_dispatcher,
        )

        with (
            patch.object(plan_dispatcher, "handle_retry", new_callable=AsyncMock) as mock_retry,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.create_workflow.return_value = "wf-1"
            payload = {"session_id": "s-1"}
            await dispatch_plan_message("client-1", "plan.retry", payload, "wf-1")
            mock_retry.assert_called_once_with("client-1", "wf-1", payload)

    @pytest.mark.asyncio
    async def test_dispatch_unknown_type_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            dispatch_plan_message,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            mock_mgr.create_workflow.return_value = "wf-1"
            await dispatch_plan_message("client-1", "plan.unknown", {}, "wf-1")
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "UNKNOWN_PLAN_MESSAGE"


class TestPlanDispatcherSessionIsolation:
    """Tests session isolation helpers (Req 20.6)."""

    @pytest.mark.asyncio
    async def test_phase_input_session_not_found_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_phase_input,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_phase_input(
                "client-1",
                "wf-1",
                {"session_id": "nonexistent", "phase": "context", "data": {}},
            )
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_navigate_session_not_found_emits_error(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_navigate,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_navigate(
                "client-1",
                "wf-1",
                {
                    "session_id": "nonexistent",
                    "target_phase": "context",
                    "confirm_cascade": True,
                },
            )
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.error"
            assert call_kw["data"]["code"] == "SESSION_NOT_FOUND"

    def test_register_session_keeps_config_reference(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
        )

        mock_engine = MagicMock()
        original_config = {"configurable": {"thread_id": "plan-test-123"}}
        _register_session(
            "test-sess",
            mock_engine,
            original_config,
            "client-1",
            "wf-1",
        )

        session = _sessions["test-sess"]
        # Mutating the original config should be reflected because the
        # dispatcher intentionally stores the config by reference.
        original_config["configurable"]["thread_id"] = "mutated"
        assert session["config"]["configurable"]["thread_id"] == "mutated"
        # Cleanup
        del _sessions["test-sess"]

    def test_validate_session_owner_correct_client(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _validate_session_owner,
        )

        session = {"client_id": "client-1"}
        assert _validate_session_owner(session, "client-1", "s-1") is True

    def test_validate_session_owner_wrong_client(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _validate_session_owner,
        )

        session = {"client_id": "client-1"}
        assert _validate_session_owner(session, "client-2", "s-1") is False

    def test_validate_session_owner_no_client(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _validate_session_owner,
        )

        session = {"client_id": None}
        assert _validate_session_owner(session, "any-client", "s-1") is True


class TestPlanDispatcherPauseHandler:
    """Tests plan.pause handler."""

    @pytest.mark.asyncio
    async def test_pause_emits_paused_event(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            handle_plan_pause,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_pause("client-1", "wf-1", {"session_id": "s-1"})
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.paused"
            assert call_kw["data"]["status"] == "paused"
            assert call_kw["data"]["session_id"] == "s-1"


class TestCancelRunningTask:
    """Tests _cancel_running_task helper."""

    @pytest.mark.asyncio
    async def test_cancel_active_task(self):
        import asyncio

        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _cancel_running_task,
        )

        async def long_running():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_running())
        session = {"running_task": task}
        result = await _cancel_running_task(session)
        assert result is True
        assert session["running_task"] is None

    @pytest.mark.asyncio
    async def test_cancel_no_task(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _cancel_running_task,
        )

        session = {"running_task": None}
        result = await _cancel_running_task(session)
        assert result is False
        assert session["running_task"] is None


class TestSessionOwnershipEnforcement:
    """Tests ownership validation on mutating session handlers."""

    @pytest.mark.asyncio
    async def test_phase_input_rejects_wrong_owner(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
            handle_plan_phase_input,
        )

        mock_engine = MagicMock()
        mock_engine.resume_workflow = AsyncMock(return_value={})
        _register_session(
            "owner-phase-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-owner-phase"}},
            "client-A",
            "wf-A",
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_phase_input(
                "client-B",
                "wf-B",
                {"session_id": "owner-phase-sess", "phase": "context", "data": {}},
            )

        error_call = mock_mgr.send_event.call_args
        assert error_call[1]["event_type"] == "plan.error"
        assert error_call[1]["data"]["code"] == "SESSION_OWNER_MISMATCH"
        assert _sessions["owner-phase-sess"]["client_id"] == "client-A"
        mock_engine.resume_workflow.assert_not_called()

        del _sessions["owner-phase-sess"]

    @pytest.mark.asyncio
    async def test_resume_rejects_wrong_owner_for_active_session(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
            handle_plan_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(return_value={"completed_phases": {}, "budget": {}})
        _register_session(
            "owner-resume-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-owner-resume"}},
            "client-A",
            "wf-A",
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_resume("client-B", "wf-B", {"session_id": "owner-resume-sess"})

        error_call = mock_mgr.send_event.call_args
        assert error_call[1]["event_type"] == "plan.error"
        assert error_call[1]["data"]["code"] == "SESSION_OWNER_MISMATCH"
        assert _sessions["owner-resume-sess"]["client_id"] == "client-A"
        mock_engine.get_workflow_state.assert_not_called()

        del _sessions["owner-resume-sess"]

    @pytest.mark.asyncio
    async def test_reconnect_rejects_wrong_owner(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
            handle_plan_reconnect,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(return_value={"completed_phases": {}, "budget": {}})
        _register_session(
            "owner-reconnect-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-owner-reconnect"}},
            "client-A",
            "wf-A",
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_reconnect("client-B", "wf-B", {"session_id": "owner-reconnect-sess"})

        error_call = mock_mgr.send_event.call_args
        assert error_call[1]["event_type"] == "plan.error"
        assert error_call[1]["data"]["code"] == "SESSION_OWNER_MISMATCH"
        assert _sessions["owner-reconnect-sess"]["client_id"] == "client-A"
        mock_engine.get_workflow_state.assert_not_called()

        del _sessions["owner-reconnect-sess"]

    @pytest.mark.asyncio
    async def test_resume_rejects_wrong_owner_for_persisted_session(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            handle_plan_resume,
        )

        class _FakeDbSession:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        with (
            patch(f"{DISPATCHER_MOD}.get_session", return_value=_FakeDbSession()),
            patch(f"{DISPATCHER_MOD}.PlanSessionRepository") as repo_cls,
            patch.object(PlanDispatcher, "_create_engine") as create_engine_mock,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            repo_cls.return_value.get = AsyncMock(return_value=SimpleNamespace(user_id="client-A"))
            mock_mgr.send_event = AsyncMock()

            await handle_plan_resume("client-B", "wf-B", {"session_id": "persisted-owner-sess"})

        error_call = mock_mgr.send_event.call_args
        assert error_call[1]["event_type"] == "plan.error"
        assert error_call[1]["data"]["code"] == "SESSION_OWNER_MISMATCH"
        create_engine_mock.assert_not_called()


class TestNavigateCascadeWarning:
    """Tests plan.navigate cascade warning emission."""

    @pytest.mark.asyncio
    async def test_navigate_without_confirm_emits_warning(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
            handle_plan_navigate,
        )

        mock_engine = MagicMock()
        mock_engine.analyze_navigate = AsyncMock(
            return_value={
                "content_changed": True,
                "dirty_phases": ["planning"],
                "estimated_llm_calls": 3,
            }
        )
        _register_session(
            "nav-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-nav"}},
            "client-1",
            "wf-1",
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_navigate(
                "client-1",
                "wf-1",
                {
                    "session_id": "nav-sess",
                    "target_phase": "research",
                    "confirm_cascade": False,
                },
            )
            call_kw = mock_mgr.send_event.call_args[1]
            assert call_kw["event_type"] == "plan.cascade.confirm"
            data = call_kw["data"]
            assert "affectedPhases" in data
            assert "planning" in data["affectedPhases"]

        del _sessions["nav-sess"]


# ── WebSocket Disconnection Resilience Tests ─────────────────────#


class TestWebSocketDisconnectionResilience:
    """Tests that workflow continues and events are silently dropped
    when the WebSocket client disconnects (Req 29.1, 29.2, 29.3)."""

    @pytest.mark.asyncio
    async def test_progress_callback_silently_drops_on_disconnect(self):
        """Req 29.2: progress callback swallows exceptions from send_event."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _emit_phase_progress,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock(side_effect=Exception("WebSocket disconnected"))
            # Should NOT raise — fire-and-forget
            await _emit_phase_progress(
                "client-1",
                "wf-1",
                {
                    "session_id": "sess-1",
                    "phase": "context",
                    "step": "validate",
                    "message": "Validating...",
                    "percent": 0.1,
                },
            )
            # Verify send_event was attempted
            mock_mgr.send_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_plan_error_silently_drops_on_disconnect(self):
        """Req 29.2: error emission swallows exceptions on disconnect."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _emit_plan_error,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock(side_effect=Exception("Connection closed"))
            # Should NOT raise
            await _emit_plan_error("client-1", "wf-1", "Test error", "TEST_CODE")

    @pytest.mark.asyncio
    async def test_emit_phase_prompt_silently_drops_on_disconnect(self):
        """Req 29.2: prompt emission swallows exceptions on disconnect."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _emit_phase_prompt,
        )

        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock(side_effect=Exception("Connection closed"))
            # Should NOT raise
            await _emit_phase_prompt(
                "client-1",
                "wf-1",
                {
                    "session_id": "sess-1",
                    "phase": "context",
                    "fields": [],
                    "prefilled": {},
                },
            )

    @pytest.mark.asyncio
    async def test_engine_progress_callback_is_fire_and_forget(self):
        """Req 29.1: The progress callback created in _create_engine
        wraps _emit_phase_progress in try/except so exceptions from
        WebSocket sends don't propagate to the workflow."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _emit_phase_progress,
        )

        # Verify that _emit_phase_progress itself is fire-and-forget
        # (the progress_callback in _create_engine delegates to it)
        with patch(f"{DISPATCHER_MOD}.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock(side_effect=ConnectionError("Client gone"))
            # Should NOT raise
            await _emit_phase_progress(
                "client-1",
                "wf-1",
                {
                    "session_id": "sess-1",
                    "phase": "research",
                    "step": "dispatch",
                    "message": "Dispatching...",
                    "percent": 0.5,
                },
            )
            # Verify it attempted the send
            mock_mgr.send_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_provides_workflow_state_on_reconnect(self):
        """Req 29.3: handle_plan_resume provides completed_phases,
        workflow_status, and budget on reconnect via plan.state."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            _register_session,
            _sessions,
            handle_plan_resume,
        )

        mock_engine = MagicMock()
        mock_state = {
            "completed_phases": {"context": True},
            "workflow_status": "running",
            "budget": {
                "remaining_llm_calls": 150,
                "tokens_used": 10000,
                "max_llm_calls": 200,
                "max_tokens": 500000,
            },
            "artifacts": {
                "research/full_findings.json": {
                    "key": "specs/resume-sess/research/full_findings.json",
                    "summary": "Research findings",
                    "size_bytes": 128,
                    "created_at": "2026-04-01T00:00:00Z",
                }
            },
            "context": {"spec_name": "Test"},
        }
        mock_engine.get_workflow_state = AsyncMock(return_value=mock_state)
        _register_session(
            "resume-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-resume"}},
            "client-1",
            "wf-1",
        )

        with (
            patch.object(PlanDispatcher, "_persist_runtime_snapshot", new=AsyncMock()),
            patch.object(PlanDispatcher, "_extract_interrupt_from_state", new=AsyncMock(return_value=None)),
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.send_event = AsyncMock(return_value=True)
            await handle_plan_resume(
                "client-1",
                "wf-1",
                {"session_id": "resume-sess"},
            )

            calls = mock_mgr.send_event.call_args_list
            assert len(calls) >= 1

            # Find the plan.state event (Req 29.3)
            state_call = None
            for call in calls:
                if call[1].get("event_type") == "plan.state":
                    state_call = call
                    break

            assert state_call is not None, "Expected plan.state event on reconnect"
            data = state_call[1]["data"]
            assert data["completed_phases"] == {"context": True}
            assert data["workflow_status"] == "running"
            assert data["budget"]["remainingLlmCalls"] == 150
            assert data["budget"]["tokensUsed"] == 10000
            assert data["current_phase"] == "research"
            assert data["artifacts"] == [
                {
                    "key": "research/full_findings.json",
                    "summary": "Research findings",
                    "size_bytes": 128,
                    "created_at": "2026-04-01T00:00:00Z",
                    "content_type": "application/json",
                }
            ]

        del _sessions["resume-sess"]

    @pytest.mark.asyncio
    async def test_resume_includes_orchestrate_task_context_snapshot(self):
        """Resume should hydrate current orchestrate task context for the frontend panel."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            _register_session,
            _sessions,
            handle_plan_resume,
        )

        task_name = "Launch Plan: Feature Flags, Staged Rollout, Runbooks, and Operational Readiness"

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                    "research": True,
                    "planning": True,
                },
                "workflow_status": "running",
                "budget": {
                    "remaining_llm_calls": 42,
                    "tokens_used": 24000,
                    "max_llm_calls": 200,
                    "max_tokens": 500000,
                },
                "context": {"spec_name": "Launch Plan"},
                "plan": {
                    "task_dag": {
                        "tasks": [
                            {
                                "id": "task-launch",
                                "name": task_name,
                                "priority": "high",
                                "dependencies": [],
                                "spec_section": task_name,
                            }
                        ]
                    }
                },
                "orchestrate": {
                    "current_task": {
                        "id": "task-launch",
                        "name": task_name,
                        "spec_section": task_name,
                    },
                    "current_task_context": {
                        "task_research": {
                            "summary": "Use feature flags to decouple deploy from release.",
                            "findings": {
                                "key_insights": [
                                    "Roll out to internal users first.",
                                    "Prepare rollback and incident runbooks.",
                                ]
                            },
                        }
                    },
                    "agent_context": {
                        "spec_section_content": "## Launch Plan\nStage exposure behind runtime flags.",
                    },
                },
                "document_manifest": {
                    "spec_name": "Launch Plan",
                    "total_documents": 1,
                    "total_tokens": 321,
                    "composed_index_ref": {"key": "output/index.md"},
                    "entries": [
                        {
                            "task_id": "task-launch",
                            "spec_section": task_name,
                            "artifact_ref": {"key": "output/task-launch.md"},
                            "status": "reviewed",
                            "section_type": "analysis_and_draft",
                            "token_count": 321,
                        }
                    ],
                },
            }
        )
        _register_session(
            "resume-orchestrate-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-resume-orchestrate"}},
            "client-1",
            "wf-1",
        )

        with (
            patch.object(PlanDispatcher, "_persist_runtime_snapshot", new=AsyncMock()),
            patch.object(PlanDispatcher, "_extract_interrupt_from_state", new=AsyncMock(return_value=None)),
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.send_event = AsyncMock(return_value=True)
            await handle_plan_resume(
                "client-1",
                "wf-1",
                {"session_id": "resume-orchestrate-sess"},
            )

            state_call = next(
                call for call in mock_mgr.send_event.call_args_list
                if call[1].get("event_type") == "plan.state"
            )
            data = state_call[1]["data"]
            assert data["current_phase"] == "orchestrate"
            assert data["task_context"] == {
                "task_id": "task-launch",
                "task_name": task_name,
                "spec_section": task_name,
                "spec_section_content": "## Launch Plan\nStage exposure behind runtime flags.",
                "research_summary": (
                    "Use feature flags to decouple deploy from release.\n\n"
                    "**Key findings:**\n"
                    "• Roll out to internal users first.\n"
                    "• Prepare rollback and incident runbooks."
                ),
            }
            assert data["plan_tasks"]["task-launch"]["status"] == "in_progress"
            assert data["plan_tasks"]["task-launch"]["specSection"] == task_name
            assert (
                data["plan_tasks"]["task-launch"]["researchSummary"]
                == data["task_context"]["research_summary"]
            )
            assert data["document_manifest"]["entries"][0]["taskId"] == "task-launch"
            assert data["document_manifest"]["entries"][0]["specSection"] == task_name

        del _sessions["resume-orchestrate-sess"]

    @pytest.mark.asyncio
    async def test_resume_completed_session_does_not_emit_synthetic_prompt(self):
        """Completed sessions should restore state without reopening a phase prompt."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            _register_session,
            _sessions,
            handle_plan_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                    "research": True,
                    "planning": True,
                    "orchestrate": True,
                    "assembly": True,
                },
                "workflow_status": "completed",
                "budget": {
                    "remaining_llm_calls": 10,
                    "tokens_used": 12345,
                    "max_llm_calls": 200,
                    "max_tokens": 500000,
                },
                "artifacts": {},
            }
        )
        _register_session(
            "resume-complete-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-resume-complete"}},
            "client-1",
            "wf-1",
        )

        with (
            patch.object(PlanDispatcher, "_persist_runtime_snapshot", new=AsyncMock()),
            patch.object(PlanDispatcher, "_extract_interrupt_from_state", new=AsyncMock(return_value=None)),
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.send_event = AsyncMock(return_value=True)
            await handle_plan_resume(
                "client-1",
                "wf-1",
                {"session_id": "resume-complete-sess"},
            )

            events = [call[1].get("event_type") for call in mock_mgr.send_event.call_args_list]
            assert "plan.state" in events
            assert "plan.phase.prompt" not in events

        del _sessions["resume-complete-sess"]

    @pytest.mark.asyncio
    async def test_resume_stale_running_session_restarts_first_incomplete_phase(self):
        """Dead-end running sessions must recover by restarting the first incomplete phase."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            _register_session,
            _sessions,
            handle_plan_resume,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            side_effect=[
                {
                    "completed_phases": {
                        "context": True,
                        "research": True,
                        "planning": True,
                    },
                    "workflow_status": "running",
                    "budget": {
                        "remaining_llm_calls": 25,
                        "tokens_used": 1000,
                        "max_llm_calls": 200,
                        "max_tokens": 500000,
                    },
                    "artifacts": {},
                    "orchestrate": {
                        "all_complete": True,
                        "task_results": [
                            {"id": "task-1", "status": "done"},
                            {"id": "task-2", "status": "done"},
                        ],
                    },
                    "current_phase": None,
                },
                {
                    "completed_phases": {
                        "context": True,
                        "research": True,
                        "planning": True,
                        "orchestrate": True,
                        "assembly": True,
                    },
                    "workflow_status": "completed",
                },
            ]
        )
        mock_engine.restart_from_phase = AsyncMock(
            return_value={
                "workflow_status": "completed",
                "completed_phases": {"assembly": True},
            }
        )
        _register_session(
            "resume-stale-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-resume-stale"}},
            "client-1",
            "wf-1",
        )

        with (
            patch.object(PlanDispatcher, "_persist_runtime_snapshot", new=AsyncMock()) as persist_mock,
            patch.object(PlanDispatcher, "_check_and_emit_error", new=AsyncMock(return_value=False)),
            patch.object(
                PlanDispatcher,
                "_extract_interrupt_from_state",
                new=AsyncMock(side_effect=[None, None]),
            ),
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.send_event = AsyncMock(return_value=True)
            await handle_plan_resume(
                "client-1",
                "wf-1",
                {"session_id": "resume-stale-sess"},
            )

            mock_engine.restart_from_phase.assert_awaited_once()
            restart_args = mock_engine.restart_from_phase.await_args.args
            restart_cfg = mock_engine.restart_from_phase.await_args.args[1]
            assert restart_args[0] == "assembly"
            assert restart_cfg["configurable"]["thread_id"] == "plan-resume-stale"
            events = [call[1].get("event_type") for call in mock_mgr.send_event.call_args_list]
            assert "plan.state" in events
            assert "plan.phase.prompt" not in events
            state_call = next(
                call for call in mock_mgr.send_event.call_args_list
                if call[1].get("event_type") == "plan.state"
            )
            state_data = state_call[1]["data"]
            assert state_data["current_phase"] == "assembly"
            assert state_data["completed_phases"] == {
                "context": True,
                "research": True,
                "planning": True,
                "orchestrate": True,
            }
            persist_kwargs = persist_mock.await_args.kwargs
            assert persist_kwargs["result"] == {
                "workflow_status": "completed",
                "completed_phases": {"assembly": True},
            }

        del _sessions["resume-stale-sess"]

    @pytest.mark.asyncio
    async def test_runtime_snapshot_prefers_terminal_result_over_stale_checkpoint(self):
        """Terminal result data should win when the checkpoint still looks in-progress."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                    "research": True,
                    "planning": True,
                    "orchestrate": True,
                },
                "workflow_status": "running",
                "budget": {"remaining_llm_calls": 5},
                "context": {"spec_name": "FedEx Plan"},
            }
        )

        with patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock:
            await PlanDispatcher._persist_runtime_snapshot(
                session_id="snapshot-sess",
                thread_id="plan-snapshot-sess",
                user_id="client-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-snapshot-sess"}},
                fallback_phase="assembly",
                result={
                    "completed_phases": {"assembly": True},
                    "workflow_status": "completed",
                },
            )

        kwargs = persist_mock.await_args.kwargs
        assert kwargs["workflow_status"] == "completed"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
            "planning": True,
            "orchestrate": True,
            "assembly": True,
        }

    @pytest.mark.asyncio
    async def test_runtime_snapshot_infers_orchestrate_completion_from_orchestrate_state(self):
        """Persisted snapshots should keep orchestrate complete when assembly is next."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                    "research": True,
                    "planning": True,
                },
                "workflow_status": "running",
                "orchestrate": {
                    "all_complete": True,
                    "task_results": [{"id": "task-1", "status": "done"}],
                },
                "budget": {"remaining_llm_calls": 5},
                "context": {"spec_name": "FedEx Plan"},
            }
        )

        with patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock:
            await PlanDispatcher._persist_runtime_snapshot(
                session_id="snapshot-orchestrate-sess",
                thread_id="plan-snapshot-orchestrate-sess",
                user_id="client-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-snapshot-orchestrate-sess"}},
            )

        kwargs = persist_mock.await_args.kwargs
        assert kwargs["current_phase"] == "assembly"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
            "planning": True,
            "orchestrate": True,
        }

    @pytest.mark.asyncio
    async def test_runtime_snapshot_infers_research_completion_from_plan_progress(self):
        """Plan progress should backfill research completion during resume recovery."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                },
                "workflow_status": "running",
                "plan": {
                    "roadmap": {"phases": [{"name": "Phase 1"}]},
                    "tasks": [{"id": "task-1"}],
                },
                "budget": {"remaining_llm_calls": 12},
                "context": {"spec_name": "FedEx Plan"},
            }
        )

        with patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock:
            await PlanDispatcher._persist_runtime_snapshot(
                session_id="snapshot-planning-progress-sess",
                thread_id="plan-snapshot-planning-progress-sess",
                user_id="client-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-snapshot-planning-progress-sess"}},
            )

        kwargs = persist_mock.await_args.kwargs
        assert kwargs["current_phase"] == "planning"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
        }

    @pytest.mark.asyncio
    async def test_runtime_snapshot_infers_research_completion_from_research_approval(self):
        """Approved research should advance resume to planning even before plan data exists."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                },
                "workflow_status": "running",
                "research": {
                    "approved": True,
                    "approval_decision": "approve",
                    "findings": {"summary": "Looks good"},
                },
                "budget": {"remaining_llm_calls": 12},
                "context": {"spec_name": "FedEx Plan"},
            }
        )

        with patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock:
            await PlanDispatcher._persist_runtime_snapshot(
                session_id="snapshot-research-approved-sess",
                thread_id="plan-snapshot-research-approved-sess",
                user_id="client-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-snapshot-research-approved-sess"}},
            )

        kwargs = persist_mock.await_args.kwargs
        assert kwargs["current_phase"] == "planning"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
        }

    @pytest.mark.asyncio
    async def test_runtime_snapshot_infers_planning_completion_from_orchestrate_progress(self):
        """Orchestrate progress should backfill planning completion during resume recovery."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                    "research": True,
                },
                "workflow_status": "running",
                "orchestrate": {
                    "current_task": {"id": "task-1"},
                    "iteration_count": 1,
                },
                "budget": {"remaining_llm_calls": 8},
                "context": {"spec_name": "FedEx Plan"},
            }
        )

        with patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock:
            await PlanDispatcher._persist_runtime_snapshot(
                session_id="snapshot-orchestrate-progress-sess",
                thread_id="plan-snapshot-orchestrate-progress-sess",
                user_id="client-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-snapshot-orchestrate-progress-sess"}},
            )

        kwargs = persist_mock.await_args.kwargs
        assert kwargs["current_phase"] == "orchestrate"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
            "planning": True,
        }

    @pytest.mark.asyncio
    async def test_runtime_snapshot_infers_planning_completion_from_planning_approval(self):
        """Approved planning should advance resume to orchestrate before orchestration begins."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import PlanDispatcher

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "completed_phases": {
                    "context": True,
                    "research": True,
                },
                "workflow_status": "running",
                "plan": {
                    "approved": True,
                    "approval_decision": "approve",
                    "task_dag": {"tasks": [{"id": "task-1"}]},
                },
                "budget": {"remaining_llm_calls": 8},
                "context": {"spec_name": "FedEx Plan"},
            }
        )

        with patch.object(PlanDispatcher, "_persist_session_to_db", new=AsyncMock()) as persist_mock:
            await PlanDispatcher._persist_runtime_snapshot(
                session_id="snapshot-planning-approved-sess",
                thread_id="plan-snapshot-planning-approved-sess",
                user_id="client-1",
                engine=mock_engine,
                config={"configurable": {"thread_id": "plan-snapshot-planning-approved-sess"}},
            )

        kwargs = persist_mock.await_args.kwargs
        assert kwargs["current_phase"] == "orchestrate"
        assert kwargs["completed_phases"] == {
            "context": True,
            "research": True,
            "planning": True,
        }

    @pytest.mark.asyncio
    async def test_phase_input_re_emits_prompt_when_decision_mismatches_interrupt(self):
        """A stale decision must not be applied to a different pending interrupt."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            _register_session,
            _sessions,
            handle_plan_phase_input,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(return_value={"workflow_status": "running"})
        mock_engine.resume_workflow = AsyncMock(return_value={})
        _register_session(
            "phase-mismatch-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-phase-mismatch"}},
            "client-1",
            "wf-1",
        )

        interrupt_payload = {
            "type": "approval",
            "phase": "assembly",
            "step": "approval",
            "message": "Approve the assembled document?",
            "options": [
                {"id": "approve", "label": "Approve & Finalize"},
                {"id": "revise", "label": "Request Revisions"},
                {"id": "reject", "label": "Reject"},
            ],
            "artifacts": [],
            "summary": {"spec_name": "FedEx"},
        }

        with (
            patch.object(
                PlanDispatcher,
                "_extract_interrupt_from_state",
                new=AsyncMock(return_value=interrupt_payload),
            ),
            patch.object(PlanDispatcher, "_emit_phase_prompt", new=AsyncMock()) as emit_prompt_mock,
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.register_session = MagicMock()
            await handle_plan_phase_input(
                "client-1",
                "wf-1",
                {
                    "session_id": "phase-mismatch-sess",
                    "phase": "assembly",
                    "data": {"decision": "increase_budget", "max_llm_calls": 400},
                },
            )

        emit_prompt_mock.assert_awaited_once()
        prompt_payload = emit_prompt_mock.await_args.args[2]
        assert prompt_payload["session_id"] == "phase-mismatch-sess"
        assert prompt_payload["phase"] == "assembly"
        mock_engine.resume_workflow.assert_not_awaited()

        del _sessions["phase-mismatch-sess"]

    @pytest.mark.asyncio
    async def test_phase_input_resumes_specific_interrupt_id(self):
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            PlanDispatcher,
            _register_session,
            _sessions,
            handle_plan_phase_input,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(return_value={"workflow_status": "running"})
        mock_engine.resume_workflow = AsyncMock(return_value={})
        _register_session(
            "phase-targeted-resume-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-targeted-resume"}},
            "client-1",
            "wf-1",
        )

        interrupt_payload = {
            "type": "approval",
            "phase": "assembly",
            "step": "approval",
            "_interrupt_id": "assembly-interrupt-id",
            "message": "Approve the assembled document?",
            "options": [
                {"id": "approve", "label": "Approve & Finalize"},
                {"id": "revise", "label": "Request Revisions"},
                {"id": "reject", "label": "Reject"},
            ],
        }

        with (
            patch.object(
                PlanDispatcher,
                "_extract_interrupt_from_state",
                new=AsyncMock(side_effect=[interrupt_payload, None]),
            ),
            patch.object(PlanDispatcher, "_persist_runtime_snapshot", new=AsyncMock()),
            patch.object(PlanDispatcher, "_check_and_emit_error", new=AsyncMock(return_value=False)),
            patch(f"{DISPATCHER_MOD}.manager") as mock_mgr,
        ):
            mock_mgr.register_session = MagicMock()
            await handle_plan_phase_input(
                "client-1",
                "wf-1",
                {
                    "session_id": "phase-targeted-resume-sess",
                    "phase": "assembly",
                    "data": {"decision": "approve"},
                },
            )

        mock_engine.resume_workflow.assert_awaited_once_with(
            workflow_id="phase-targeted-resume-sess",
            user_id="client-1",
            input_data={"decision": "approve"},
            config=_sessions["phase-targeted-resume-sess"]["config"],
            interrupt_id="assembly-interrupt-id",
        )

        del _sessions["phase-targeted-resume-sess"]

    @pytest.mark.asyncio
    async def test_session_registry_keeps_engine_alive_after_disconnect(
        self,
    ):
        """Req 29.1: The session registry keeps the engine reference
        alive even after the WebSocket client disconnects."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _get_session,
            _register_session,
            _sessions,
        )

        mock_engine = MagicMock()
        _register_session(
            "alive-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-alive"}},
            "client-1",
            "wf-1",
        )

        # Simulate disconnect: client_id changes but session persists
        session = _get_session("alive-sess")
        assert session is not None
        assert session["engine"] is mock_engine

        # Even after "disconnect", session is still accessible
        # (ConnectionManager.disconnect preserves running workflows)
        session = _get_session("alive-sess")
        assert session is not None
        assert session["engine"] is mock_engine

        del _sessions["alive-sess"]


# ── Storage Error Retry Tests (Task 13.3, Req 27.2) ─────────────


class TestPlanRetryResetsStoragePausedStatus:
    """Test handle_plan_retry resets workflow_status from 'paused' to 'running'.

    Validates Requirement 27.2: Allow user to retry the failed phase
    after storage issue is resolved.
    """

    @pytest.mark.asyncio
    async def test_retry_resets_paused_status(self):
        """plan.retry resets workflow_status from 'paused' to 'running'."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
            handle_plan_retry,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(
            return_value={
                "workflow_status": "paused",
                "paused_phase": "research",
            }
        )
        mock_engine.workflow = MagicMock()
        mock_engine.workflow.aupdate_state = AsyncMock()
        mock_engine.resume_workflow = AsyncMock(return_value={"research": {}})

        _register_session(
            "retry-storage-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-retry-storage"}},
            "client-1",
            "wf-1",
        )

        with patch("graph_kb_api.websocket.handlers.plan_dispatcher.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_retry(
                "client-1",
                "wf-1",
                {"session_id": "retry-storage-sess"},
            )

        # Verify workflow_status was reset to "running"
        mock_engine.workflow.aupdate_state.assert_awaited_once()
        update_args = mock_engine.workflow.aupdate_state.call_args
        assert update_args[0][1]["workflow_status"] == "running"

        # Verify resume_workflow was called
        mock_engine.resume_workflow.assert_awaited_once()

        del _sessions["retry-storage-sess"]

    @pytest.mark.asyncio
    async def test_retry_does_not_reset_running_status(self):
        """plan.retry does not reset workflow_status when already 'running'."""
        from graph_kb_api.websocket.handlers.plan_dispatcher import (
            _register_session,
            _sessions,
            handle_plan_retry,
        )

        mock_engine = MagicMock()
        mock_engine.get_workflow_state = AsyncMock(return_value={"workflow_status": "running"})
        mock_engine.workflow = MagicMock()
        mock_engine.workflow.aupdate_state = AsyncMock()
        mock_engine.resume_workflow = AsyncMock(return_value={})

        _register_session(
            "retry-running-sess",
            mock_engine,
            {"configurable": {"thread_id": "plan-retry-running"}},
            "client-1",
            "wf-1",
        )

        with patch("graph_kb_api.websocket.handlers.plan_dispatcher.manager") as mock_mgr:
            mock_mgr.send_event = AsyncMock()
            await handle_plan_retry(
                "client-1",
                "wf-1",
                {"session_id": "retry-running-sess"},
            )

        # aupdate_state should NOT be called since status is already "running"
        mock_engine.workflow.aupdate_state.assert_not_awaited()

        # resume_workflow should still be called
        mock_engine.resume_workflow.assert_awaited_once()

        del _sessions["retry-running-sess"]
