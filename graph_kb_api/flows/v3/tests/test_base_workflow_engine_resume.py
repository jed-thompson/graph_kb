from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from langgraph.types import Command


@pytest.mark.asyncio
async def test_resume_workflow_skips_stale_interrupt_cancellation_for_targeted_resume() -> None:
    compiled_workflow = SimpleNamespace(ainvoke=AsyncMock(return_value={"ok": True}))
    dummy_engine = SimpleNamespace(
        workflow_name="dummy",
        compiled_workflow=compiled_workflow,
        _cancel_stale_interrupts=AsyncMock(),
    )

    result = await BaseWorkflowEngine.resume_workflow(
        dummy_engine,
        workflow_id="wf-1",
        user_id="user-1",
        input_data={"decision": "approve"},
        config={"configurable": {"thread_id": "thread-1"}},
        interrupt_id="interrupt-123",
    )

    assert result == {"ok": True}
    dummy_engine._cancel_stale_interrupts.assert_not_awaited()

    command = compiled_workflow.ainvoke.await_args.args[0]
    assert isinstance(command, Command)
    assert command.resume == {"interrupt-123": {"decision": "approve"}}


@pytest.mark.asyncio
async def test_resume_workflow_cancels_stale_interrupts_for_generic_resume() -> None:
    compiled_workflow = SimpleNamespace(ainvoke=AsyncMock(return_value={"ok": True}))
    dummy_engine = SimpleNamespace(
        workflow_name="dummy",
        compiled_workflow=compiled_workflow,
        _cancel_stale_interrupts=AsyncMock(return_value=1),
    )

    await BaseWorkflowEngine.resume_workflow(
        dummy_engine,
        workflow_id="wf-1",
        user_id="user-1",
        input_data={"decision": "approve"},
        config={"configurable": {"thread_id": "thread-1"}},
    )

    dummy_engine._cancel_stale_interrupts.assert_awaited_once()
