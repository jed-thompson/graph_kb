"""Regression tests for Plan command bug fixes.

Tests cover:
1. emit_task_critique includes task_name, score, iteration
2. WorkerNode emits agent_content with LLM output
3. CritiqueNode does NOT auto-approve on exception
4. emit_manifest_update exists and emits correct event
5. Critique prompt includes pragmatic guidance
6. emit_manifest_update is imported in orchestrate_nodes (prevents silent NameError)
7. WorkerNode emits agent_content via emit_phase_progress
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock

import pytest

# ── Bug 1: emit_task_critique includes task_name ──────────────────────


class TestEmitTaskCritiqueIncludesTaskName:
    """Regression: emit_task_critique must include task_name in payload."""

    @pytest.fixture(autouse=True)
    def setup_ws_manager(self):
        from graph_kb_api.websocket import plan_events

        self.mock_manager = AsyncMock()
        plan_events.set_plan_ws_manager(self.mock_manager)
        yield
        plan_events.set_plan_ws_manager(None)

    @pytest.mark.asyncio
    async def test_task_name_included_in_payload(self):
        from graph_kb_api.websocket.plan_events import emit_task_critique

        await emit_task_critique(
            session_id="sess-1",
            task_id="task-1",
            passed=False,
            feedback="Needs more detail",
            client_id="client-1",
            task_name="Authentication Flow",
            score=0.4,
            iteration=2,
        )

        self.mock_manager.send_event.assert_called_once()
        call_kwargs = self.mock_manager.send_event.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["task_name"] == "Authentication Flow"
        assert data["score"] == 0.4
        assert data["iteration"] == 2

    @pytest.mark.asyncio
    async def test_task_name_omitted_when_none(self):
        from graph_kb_api.websocket.plan_events import emit_task_critique

        await emit_task_critique(
            session_id="sess-1",
            task_id="task-1",
            passed=True,
            feedback="",
            client_id="client-1",
        )

        self.mock_manager.send_event.assert_called_once()
        call_kwargs = self.mock_manager.send_event.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert "task_name" not in data
        assert "score" not in data


# ── Bug 3: CritiqueNode does NOT auto-approve on exception ───────────


class TestCritiqueNodeNoAutoApprove:
    """Regression: CritiqueNode must NOT set approved=True when critique fails."""

    def test_exception_handler_returns_not_approved(self):
        """Verify the CritiqueNode exception path does not auto-approve."""
        from graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes import CritiqueNode

        source = inspect.getsource(CritiqueNode._execute_step)

        # The old bug had: "approved": True, "score": 0.7, "Auto-approved"
        # After fix: "approved": False, "score": 0.0
        # Ensure the auto-approve pattern is gone
        assert "Auto-approved" not in source, (
            "CritiqueNode still has auto-approve on exception — this silently bypasses the quality gate"
        )


# ── Bug 4: emit_manifest_update exists ───────────────────────────────


class TestEmitManifestUpdate:
    """Regression: emit_manifest_update must exist and emit correct event."""

    @pytest.fixture(autouse=True)
    def setup_ws_manager(self):
        from graph_kb_api.websocket import plan_events

        self.mock_manager = AsyncMock()
        plan_events.set_plan_ws_manager(self.mock_manager)
        yield
        plan_events.set_plan_ws_manager(None)

    @pytest.mark.asyncio
    async def test_emit_manifest_update_exists(self):
        from graph_kb_api.websocket.plan_events import emit_manifest_update

        assert callable(emit_manifest_update)

    @pytest.mark.asyncio
    async def test_emit_manifest_update_sends_correct_event(self):
        from graph_kb_api.websocket.plan_events import emit_manifest_update

        await emit_manifest_update(
            session_id="sess-1",
            manifest_entry={
                "taskId": "task-1",
                "specSection": "5.3 Rates",
                "status": "reviewed",
                "tokenCount": 1500,
            },
            total_documents=3,
            total_tokens=4500,
            client_id="client-1",
        )

        self.mock_manager.send_event.assert_called_once()
        call_kwargs = self.mock_manager.send_event.call_args
        event_type = call_kwargs.kwargs.get("event_type") or call_kwargs[1].get("event_type")
        assert event_type == "plan.manifest.update"
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["entry"]["taskId"] == "task-1"
        assert data["total_documents"] == 3

    @pytest.mark.asyncio
    async def test_emit_manifest_update_graceful_without_ws(self):
        from graph_kb_api.websocket import plan_events

        plan_events.set_plan_ws_manager(None)

        from graph_kb_api.websocket.plan_events import emit_manifest_update

        # Should not raise
        await emit_manifest_update(
            session_id="sess-1",
            manifest_entry={"taskId": "task-1"},
            total_documents=1,
            total_tokens=100,
        )


# ── Bug 5: Critique prompt is pragmatic ──────────────────────────────


class TestCritiquePromptPragmatic:
    """Regression: Critique prompt must include pragmatic approval guidance."""

    def test_prompt_includes_pragmatic_guidance(self):
        from graph_kb_api.flows.v3.agents.personas.prompt_manager import (
            get_agent_prompt_manager,
        )

        prompt = get_agent_prompt_manager().get_prompt("architect_critique")
        assert "pragmatic" in prompt.lower() or "good enough" in prompt.lower(), (
            "Critique prompt lacks pragmatic approval guidance — this causes excessive rejections"
        )

    def test_prompt_includes_task_name_placeholder(self):
        from graph_kb_api.flows.v3.agents.personas.prompt_manager import (
            get_agent_prompt_manager,
        )

        prompt = get_agent_prompt_manager().get_prompt("architect_critique")
        assert "{task_name}" in prompt, "Critique prompt missing {task_name} placeholder"

    def test_prompt_includes_scoring_guide(self):
        from graph_kb_api.flows.v3.agents.personas.prompt_manager import (
            get_agent_prompt_manager,
        )

        prompt = get_agent_prompt_manager().get_prompt("architect_critique")
        assert "Scoring Guide" in prompt or "scoring" in prompt.lower(), "Critique prompt missing scoring guide"


# ── Bug 6: emit_manifest_update is imported in orchestrate_nodes ─────


class TestEmitManifestUpdateImported:
    """Regression: emit_manifest_update must be importable from orchestrate_nodes module scope.

    The previous fix added the call but forgot the import, causing a silent
    NameError caught by try/except — making progressive manifest emission dead code.
    """

    def test_emit_manifest_update_in_module_imports(self):
        """Verify emit_manifest_update is in the module's import block."""
        import graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes as mod

        source = inspect.getsource(mod)
        # Check the import block contains emit_manifest_update
        assert "emit_manifest_update" in source.split("logger")[0], (
            "emit_manifest_update is not imported at module level in orchestrate_nodes.py — "
            "the WorkerNode call will silently fail with NameError"
        )

    def test_emit_manifest_update_callable_from_module(self):
        """Verify emit_manifest_update is accessible in the module namespace."""
        from graph_kb_api.flows.v3.nodes.plan import orchestrate_nodes

        # If the import is missing, this will fail
        assert hasattr(orchestrate_nodes, "emit_manifest_update") or (
            "emit_manifest_update" in dir(orchestrate_nodes)
        ), "emit_manifest_update not found in orchestrate_nodes namespace"


# ── Bug 7: WorkerNode emits agent_content ────────────────────────────


class TestWorkerNodeEmitsAgentContent:
    """Regression: WorkerNode must emit agent_content via emit_phase_progress."""

    def test_worker_node_passes_agent_content(self):
        """Verify WorkerNode._execute_step calls emit_phase_progress with agent_content."""
        from graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes import WorkerNode

        source = inspect.getsource(WorkerNode._execute_step)
        assert "agent_content=" in source, (
            "WorkerNode._execute_step does not pass agent_content to emit_phase_progress — "
            "users cannot see LLM output during orchestration"
        )

    def test_worker_node_truncates_agent_content(self):
        """Verify WorkerNode truncates agent_content to avoid oversized WebSocket frames."""
        from graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes import WorkerNode

        source = inspect.getsource(WorkerNode._execute_step)
        assert "4000" in source or "[:4000]" in source, (
            "WorkerNode does not truncate agent_content — risk of oversized WebSocket frames"
        )
