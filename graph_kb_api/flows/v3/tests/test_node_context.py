"""Tests for NodeContext dataclass and SubgraphAwareNode._unpack()."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock

import pytest

from graph_kb_api.flows.v3.nodes.subgraph_aware_node import NodeContext, SubgraphAwareNode


# ---------------------------------------------------------------------------
# Concrete test node (SubgraphAwareNode is abstract)
# ---------------------------------------------------------------------------

class _TestNode(SubgraphAwareNode):
    def __init__(self, phase: str = "research"):
        self.phase = phase
        self.step_name = "test_step"
        self.step_progress = 0.0

    async def _execute_step(self, state, config):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    *,
    llm=None,
    artifact_service=None,
    workflow_context=None,
    client_id=None,
    progress_callback=None,
    services=None,
):
    """Build a RunnableConfig dict with the given configurable fields."""
    configurable = {}
    if llm is not None:
        configurable["llm"] = llm
    if artifact_service is not None:
        configurable["artifact_service"] = artifact_service
    if workflow_context is not None:
        configurable["context"] = workflow_context
    if client_id is not None:
        configurable["client_id"] = client_id
    if progress_callback is not None:
        configurable["progress_callback"] = progress_callback
    if services is not None:
        configurable["services"] = services
    return {"configurable": configurable}


# ---------------------------------------------------------------------------
# NodeContext frozen immutability
# ---------------------------------------------------------------------------

class TestNodeContextFrozen:
    def test_is_frozen(self):
        ctx = NodeContext(
            services={},
            session_id="s1",
            budget={},
            phase="research",
            config={},
            configurable={},
            llm=None,
            artifact_service=None,
            workflow_context=None,
            client_id=None,
            progress_cb=None,
            db_session_factory=None,
        )
        with pytest.raises(FrozenInstanceError):
            ctx.session_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# require_llm property
# ---------------------------------------------------------------------------

class TestRequireLlm:
    def test_raises_when_llm_is_none(self):
        ctx = NodeContext(
            services={},
            session_id="",
            budget={},
            phase="research",
            config={},
            configurable={},
            llm=None,
            artifact_service=None,
            workflow_context=None,
            client_id=None,
            progress_cb=None,
            db_session_factory=None,
        )
        with pytest.raises(RuntimeError, match="LLM service not available"):
            ctx.require_llm

    def test_returns_llm_when_present(self):
        mock_llm = MagicMock()
        ctx = NodeContext(
            services={},
            session_id="",
            budget={},
            phase="research",
            config={},
            configurable={},
            llm=mock_llm,
            artifact_service=None,
            workflow_context=None,
            client_id=None,
            progress_cb=None,
            db_session_factory=None,
        )
        assert ctx.require_llm is mock_llm


# ---------------------------------------------------------------------------
# _unpack() — full config
# ---------------------------------------------------------------------------

class TestUnpackFullConfig:
    def test_extracts_all_fields(self):
        node = _TestNode(phase="planning")
        mock_llm = MagicMock()
        mock_artifact = MagicMock()
        mock_progress = AsyncMock()
        mock_app_ctx = MagicMock()
        mock_wf_ctx = MagicMock()
        mock_wf_ctx.app_context = mock_app_ctx

        state = {
            "session_id": "sess-123",
            "budget": {"remaining_llm_calls": 10, "tokens_used": 500},
        }
        config = _make_config(
            llm=mock_llm,
            artifact_service=mock_artifact,
            workflow_context=mock_wf_ctx,
            client_id="client-abc",
            progress_callback=mock_progress,
            services={"app_context": mock_app_ctx},
        )

        ctx = node._unpack(state, config)

        assert ctx.session_id == "sess-123"
        assert ctx.budget == {"remaining_llm_calls": 10, "tokens_used": 500}
        assert ctx.phase == "planning"
        assert ctx.llm is mock_llm
        assert ctx.artifact_service is mock_artifact
        assert ctx.workflow_context is mock_wf_ctx
        assert ctx.client_id == "client-abc"
        assert ctx.progress_cb is mock_progress
        assert ctx.db_session_factory is mock_app_ctx
        assert ctx.services == {"app_context": mock_app_ctx}
        assert ctx.config is config


# ---------------------------------------------------------------------------
# _unpack() — missing optional fields get sensible defaults
# ---------------------------------------------------------------------------

class TestUnpackDefaults:
    def test_empty_state_and_config(self):
        node = _TestNode(phase="context")
        ctx = node._unpack({}, {})

        assert ctx.session_id == ""
        assert ctx.budget == {}
        assert ctx.phase == "context"
        assert ctx.llm is None
        assert ctx.artifact_service is None
        assert ctx.workflow_context is None
        assert ctx.client_id is None
        assert ctx.progress_cb is None
        assert ctx.db_session_factory is None
        assert ctx.services == {}

    def test_missing_session_id_defaults_to_empty_string(self):
        node = _TestNode()
        ctx = node._unpack({"budget": {"remaining_llm_calls": 5}}, {"configurable": {}})
        assert ctx.session_id == ""

    def test_missing_budget_defaults_to_empty_dict(self):
        node = _TestNode()
        ctx = node._unpack({"session_id": "s1"}, {"configurable": {}})
        assert ctx.budget == {}

    def test_workflow_context_without_app_context(self):
        """When workflow_context exists but has no app_context, db_session_factory is None."""
        node = _TestNode()
        mock_wf_ctx = MagicMock(spec=[])  # no attributes
        config = _make_config(workflow_context=mock_wf_ctx)
        ctx = node._unpack({}, config)
        assert ctx.workflow_context is mock_wf_ctx
        assert ctx.db_session_factory is None

    def test_workflow_context_with_none_app_context(self):
        """When workflow_context.app_context is None, db_session_factory is None."""
        node = _TestNode()
        mock_wf_ctx = MagicMock()
        mock_wf_ctx.app_context = None
        config = _make_config(workflow_context=mock_wf_ctx)
        ctx = node._unpack({}, config)
        assert ctx.db_session_factory is None

    def test_phase_comes_from_node_not_state(self):
        """Phase is always taken from self.phase, not from state."""
        node = _TestNode(phase="assembly")
        ctx = node._unpack({"phase": "research"}, {})
        assert ctx.phase == "assembly"
