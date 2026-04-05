from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from graph_kb_api.flows.v3.agents.validation_agent import (
    ValidationAgent,
    ValidationResult,
)


def _validation_result() -> ValidationResult:
    return ValidationResult(
        is_valid=True,
        issues=[],
        quality_score=0.9,
        completeness_score=0.85,
        summary="Validation passed",
        recommendations=[],
    )


@pytest.mark.asyncio
async def test_execute_reads_document_and_requirements_from_task_context(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = ValidationAgent()
    validate_document = AsyncMock(return_value=_validation_result())
    monkeypatch.setattr(agent, "_validate_document", validate_document)

    document = {"title": "FedEx Spec", "sections": {"Intro": "Hello"}}
    requirements = [{"type": "spec_name", "description": "FedEx"}]
    task = {
        "description": "Validate assembled specification document",
        "task_id": "validation_task",
        "context": {
            "document": document,
            "requirements": requirements,
        },
    }
    state = {"available_tools": []}
    workflow_context = object()

    result = await agent.execute(task=task, state=state, workflow_context=workflow_context)

    validate_document.assert_awaited_once_with(document, requirements, workflow_context, state)
    assert result["is_valid"] is True


@pytest.mark.asyncio
async def test_execute_prefers_top_level_document_fields_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = ValidationAgent()
    validate_document = AsyncMock(return_value=_validation_result())
    monkeypatch.setattr(agent, "_validate_document", validate_document)

    top_level_document = {"title": "Top Level"}
    top_level_requirements = [{"type": "top_level", "description": "Preferred"}]
    task = {
        "description": "Validate assembled specification document",
        "task_id": "validation_task",
        "document": top_level_document,
        "requirements": top_level_requirements,
        "context": {
            "document": {"title": "Nested"},
            "requirements": [{"type": "nested", "description": "Fallback"}],
        },
    }
    state = {"available_tools": []}
    workflow_context = object()

    await agent.execute(task=task, state=state, workflow_context=workflow_context)

    validate_document.assert_awaited_once_with(
        top_level_document,
        top_level_requirements,
        workflow_context,
        state,
    )
