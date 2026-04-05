"""
Tests for handler engine instantiation in WebSocket workflow handlers.

Validates Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6.
"""

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

from graph_kb_api.websocket.protocol import (
    AskCodePayload,
    DeepAgentPayload,
    MultiAgentPayload,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_app_context():
    ctx = MagicMock()
    ctx.llm = MagicMock(name="mock_llm_service")
    return ctx


def _make_mock_engine():
    engine = MagicMock()

    async def _stream(**kwargs):
        yield {"validate": {"result": "ok"}}

    engine.start_workflow_stream = _stream
    return engine


def _make_mock_facade():
    facade = MagicMock()
    facade.retrieval_service.retrieve.return_value = MagicMock(context_items=[])
    return facade


def _inject_engine_module(module_path, class_name, engine_cls):
    """Inject a mock module into sys.modules so local imports resolve."""
    mock_module = MagicMock()
    setattr(mock_module, class_name, engine_cls)
    parts = module_path.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            sys.modules[parent] = MagicMock()
    sys.modules[module_path] = mock_module
    return mock_module


def _cleanup_engine_module(module_path):
    """Remove injected mock module from sys.modules."""
    sys.modules.pop(module_path, None)


def _make_broken_module(module_path):
    """Create a module whose attribute access raises ImportError."""
    broken = types.ModuleType(module_path)

    def _raise(*args, **kwargs):
        raise ImportError("not available")

    broken.__getattr__ = _raise
    return broken


# ===================================================================
# Ask-Code handler tests — Requirements 2.1, 2.2
# ===================================================================


class TestAskCodeHandlerInstantiation:
    ENGINE_MODULE = "graph_kb_api.flows.v3.graphs.ask_code"
    ENGINE_CLASS = "AskCodeWorkflowEngine"

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.stream_workflow_with_progress")
    def test_engine_created_with_llm_app_context_checkpointer(
        self, mock_stream, mock_mgr
    ):
        """Req 2.1: engine instantiated with (llm, app_context, checkpointer)."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        mock_stream.return_value = {"final_output": "answer"}

        mock_ctx = _make_mock_app_context()
        mock_engine_cls = MagicMock(return_value=_make_mock_engine())

        _inject_engine_module(self.ENGINE_MODULE, self.ENGINE_CLASS, mock_engine_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_ask_code_workflow

                asyncio.run(
                    handle_ask_code_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=AskCodePayload(query="test", repo_id="repo1"),
                    )
                )

            mock_engine_cls.assert_called_once_with(
                llm=mock_ctx.llm,
                app_context=mock_ctx,
                checkpointer=None,
            )
        finally:
            _cleanup_engine_module(self.ENGINE_MODULE)

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.stream_workflow_with_progress")
    def test_uses_stream_workflow_with_progress(self, mock_stream, mock_mgr):
        """Req 2.2: handler uses stream_workflow_with_progress, not engine.run."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        mock_stream.return_value = {"final_output": "answer"}

        mock_ctx = _make_mock_app_context()
        mock_engine_cls = MagicMock(return_value=_make_mock_engine())

        _inject_engine_module(self.ENGINE_MODULE, self.ENGINE_CLASS, mock_engine_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_ask_code_workflow

                asyncio.run(
                    handle_ask_code_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=AskCodePayload(query="test", repo_id="repo1"),
                    )
                )

            mock_stream.assert_called_once()
            call_kwargs = mock_stream.call_args.kwargs
            assert call_kwargs["has_cycles"] is False
        finally:
            _cleanup_engine_module(self.ENGINE_MODULE)


# ===================================================================
# Deep Agent handler tests — Requirement 2.3
# ===================================================================


class TestDeepAgentHandlerInstantiation:
    ENGINE_MODULE = "graph_kb_api.flows.v3.graphs.deep_agent"
    ENGINE_CLASS = "DeepAgentWorkflowEngine"

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.stream_workflow_with_progress")
    def test_imports_deep_agent_engine_not_ask_code(self, mock_stream, mock_mgr):
        """Req 2.3: imports DeepAgentWorkflowEngine, not AskCodeWorkflowEngine."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        mock_stream.return_value = {"final_output": "deep answer"}

        mock_ctx = _make_mock_app_context()
        mock_deep_cls = MagicMock(return_value=_make_mock_engine())

        _inject_engine_module(self.ENGINE_MODULE, self.ENGINE_CLASS, mock_deep_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_deep_agent_workflow

                asyncio.run(
                    handle_deep_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=DeepAgentPayload(query="deep", repo_id="repo1"),
                    )
                )

            mock_deep_cls.assert_called_once_with(
                llm=mock_ctx.llm,
                app_context=mock_ctx,
                checkpointer=None,
            )
        finally:
            _cleanup_engine_module(self.ENGINE_MODULE)

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.stream_workflow_with_progress")
    def test_deep_handler_uses_deep_agent_node_phases(self, mock_stream, mock_mgr):
        """Req 2.3: deep handler passes DEEP_AGENT_NODE_PHASES to streaming."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        mock_stream.return_value = {"final_output": "result"}

        mock_ctx = _make_mock_app_context()
        mock_cls = MagicMock(return_value=_make_mock_engine())

        _inject_engine_module(self.ENGINE_MODULE, self.ENGINE_CLASS, mock_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import (
                    DEEP_AGENT_NODE_PHASES,
                    handle_deep_agent_workflow,
                )

                asyncio.run(
                    handle_deep_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=DeepAgentPayload(query="q", repo_id="r"),
                    )
                )

            call_kwargs = mock_stream.call_args.kwargs
            assert call_kwargs["node_phase_map"] is DEEP_AGENT_NODE_PHASES
        finally:
            _cleanup_engine_module(self.ENGINE_MODULE)


# ===================================================================
# Multi-Agent handler tests — Requirements 2.4, 2.5
# ===================================================================


class TestMultiAgentHandlerInstantiation:
    ENGINE_MODULE = "graph_kb_api.flows.v3.graphs.multi_agent"
    ENGINE_CLASS = "MultiAgentWorkflowEngine"

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.stream_workflow_with_progress")
    def test_uses_get_app_context_not_facade(self, mock_stream, mock_mgr):
        """Req 2.4: obtains llm and app_context from get_app_context()."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        mock_stream.return_value = {"formatted_output": "result"}

        mock_ctx = _make_mock_app_context()
        mock_cls = MagicMock(return_value=_make_mock_engine())

        _inject_engine_module(self.ENGINE_MODULE, self.ENGINE_CLASS, mock_cls)
        try:
            with patch(
                "graph_kb_api.context.get_app_context", return_value=mock_ctx
            ) as mock_get_ctx:
                from graph_kb_api.websocket.handlers import handle_multi_agent_workflow

                asyncio.run(
                    handle_multi_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=MultiAgentPayload(query="multi", repo_id="repo1"),
                    )
                )

            mock_get_ctx.assert_called()
            mock_cls.assert_called_once_with(
                llm=mock_ctx.llm,
                app_context=mock_ctx,
                checkpointer=None,
            )
        finally:
            _cleanup_engine_module(self.ENGINE_MODULE)

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.stream_workflow_with_progress")
    def test_multi_agent_uses_has_cycles_true(self, mock_stream, mock_mgr):
        """Req 2.5: multi-agent handler passes has_cycles=True."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        mock_stream.return_value = {"formatted_output": "result"}

        mock_ctx = _make_mock_app_context()
        mock_cls = MagicMock(return_value=_make_mock_engine())

        _inject_engine_module(self.ENGINE_MODULE, self.ENGINE_CLASS, mock_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_multi_agent_workflow

                asyncio.run(
                    handle_multi_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=MultiAgentPayload(query="q", repo_id="r"),
                    )
                )

            call_kwargs = mock_stream.call_args.kwargs
            assert call_kwargs["has_cycles"] is True
        finally:
            _cleanup_engine_module(self.ENGINE_MODULE)


# ===================================================================
# Fallback behavior tests — Requirement 2.6
# ===================================================================


class TestFallbackOnImportError:
    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    def test_ask_code_fallback_on_import_error(self, mock_facade_fn, mock_mgr):
        """Req 2.6: ImportError triggers fallback with progress and completion."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        progress_cb = AsyncMock()
        mock_mgr.create_progress_callback = MagicMock(return_value=progress_cb)
        mock_facade_fn.return_value = _make_mock_facade()
        mock_ctx = _make_mock_app_context()

        mod_path = "graph_kb_api.flows.v3.graphs.ask_code"
        saved = sys.modules.pop(mod_path, None)
        try:
            sys.modules[mod_path] = _make_broken_module(mod_path)
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_ask_code_workflow

                asyncio.run(
                    handle_ask_code_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=AskCodePayload(query="test", repo_id="repo1"),
                    )
                )

            mock_mgr.create_progress_callback.assert_called_once()
            mock_mgr.complete_workflow.assert_called_once()
            complete_calls = [
                c
                for c in mock_mgr.send_event.call_args_list
                if c.kwargs.get("event_type") == "complete"
            ]
            assert len(complete_calls) >= 1
        finally:
            sys.modules.pop(mod_path, None)
            if saved is not None:
                sys.modules[mod_path] = saved

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    def test_ask_code_fallback_on_type_error(self, mock_facade_fn, mock_mgr):
        """Req 2.6: TypeError from constructor triggers fallback."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        progress_cb = AsyncMock()
        mock_mgr.create_progress_callback = MagicMock(return_value=progress_cb)
        mock_facade_fn.return_value = _make_mock_facade()
        mock_ctx = _make_mock_app_context()

        mod_path = "graph_kb_api.flows.v3.graphs.ask_code"
        mock_cls = MagicMock(side_effect=TypeError("wrong args"))
        _inject_engine_module(mod_path, "AskCodeWorkflowEngine", mock_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_ask_code_workflow

                asyncio.run(
                    handle_ask_code_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=AskCodePayload(query="test", repo_id="repo1"),
                    )
                )

            mock_mgr.create_progress_callback.assert_called_once()
            mock_mgr.complete_workflow.assert_called_once()
        finally:
            _cleanup_engine_module(mod_path)

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    def test_deep_agent_fallback_on_import_error(self, mock_facade_fn, mock_mgr):
        """Req 2.6: deep agent falls back on ImportError."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        progress_cb = AsyncMock()
        mock_mgr.create_progress_callback = MagicMock(return_value=progress_cb)
        mock_facade_fn.return_value = _make_mock_facade()
        mock_ctx = _make_mock_app_context()

        mod_path = "graph_kb_api.flows.v3.graphs.deep_agent"
        saved = sys.modules.pop(mod_path, None)
        try:
            sys.modules[mod_path] = _make_broken_module(mod_path)
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_deep_agent_workflow

                asyncio.run(
                    handle_deep_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=DeepAgentPayload(query="test", repo_id="repo1"),
                    )
                )

            mock_mgr.create_progress_callback.assert_called_once()
            mock_mgr.complete_workflow.assert_called_once()
            complete_calls = [
                c
                for c in mock_mgr.send_event.call_args_list
                if c.kwargs.get("event_type") == "complete"
            ]
            assert len(complete_calls) >= 1
        finally:
            sys.modules.pop(mod_path, None)
            if saved is not None:
                sys.modules[mod_path] = saved

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    def test_multi_agent_fallback_on_import_error(self, mock_facade_fn, mock_mgr):
        """Req 2.6: multi-agent falls back on ImportError."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        progress_cb = AsyncMock()
        mock_mgr.create_progress_callback = MagicMock(return_value=progress_cb)
        mock_facade_fn.return_value = _make_mock_facade()
        mock_ctx = _make_mock_app_context()

        mod_path = "graph_kb_api.flows.v3.graphs.multi_agent"
        saved = sys.modules.pop(mod_path, None)
        try:
            sys.modules[mod_path] = _make_broken_module(mod_path)
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_multi_agent_workflow

                asyncio.run(
                    handle_multi_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=MultiAgentPayload(query="test", repo_id="repo1"),
                    )
                )

            mock_mgr.create_progress_callback.assert_called_once()
            mock_mgr.complete_workflow.assert_called_once()
            complete_calls = [
                c
                for c in mock_mgr.send_event.call_args_list
                if c.kwargs.get("event_type") == "complete"
            ]
            assert len(complete_calls) >= 1
        finally:
            sys.modules.pop(mod_path, None)
            if saved is not None:
                sys.modules[mod_path] = saved

    @patch("graph_kb_api.websocket.handlers.manager")
    @patch("graph_kb_api.websocket.handlers.get_graph_kb_facade")
    def test_multi_agent_fallback_on_type_error(self, mock_facade_fn, mock_mgr):
        """Req 2.6: multi-agent falls back on TypeError."""
        mock_mgr.send_event = AsyncMock(return_value=True)
        mock_mgr.complete_workflow = AsyncMock()
        progress_cb = AsyncMock()
        mock_mgr.create_progress_callback = MagicMock(return_value=progress_cb)
        mock_facade_fn.return_value = _make_mock_facade()
        mock_ctx = _make_mock_app_context()

        mod_path = "graph_kb_api.flows.v3.graphs.multi_agent"
        mock_cls = MagicMock(side_effect=TypeError("bad constructor"))
        _inject_engine_module(mod_path, "MultiAgentWorkflowEngine", mock_cls)
        try:
            with patch("graph_kb_api.context.get_app_context", return_value=mock_ctx):
                from graph_kb_api.websocket.handlers import handle_multi_agent_workflow

                asyncio.run(
                    handle_multi_agent_workflow(
                        client_id="c1",
                        workflow_id="wf1",
                        payload=MultiAgentPayload(query="test", repo_id="repo1"),
                    )
                )

            mock_mgr.create_progress_callback.assert_called_once()
            mock_mgr.complete_workflow.assert_called_once()
        finally:
            _cleanup_engine_module(mod_path)
