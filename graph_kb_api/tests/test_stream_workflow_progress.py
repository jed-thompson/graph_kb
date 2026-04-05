"""
Tests for stream_workflow_with_progress().

Validates Requirements 3.2, 3.3, 3.4.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from graph_kb_api.websocket.progress import stream_workflow_with_progress


def _make_engine(chunks):
    """Create a mock engine whose start_workflow_stream yields *chunks*.

    Each chunk should be a dict like ``{"node_name": {"key": "value"}}``.
    """
    engine = MagicMock()

    async def _stream(**kwargs):
        for c in chunks:
            yield c

    engine.start_workflow_stream = _stream
    return engine


NODE_PHASES = {
    "validate": "validating",
    "retrieve": "retrieving",
    "agent": "reasoning",
    "format": "formatting",
}


class TestStreamWorkflowSkipsEnd:
    """Req 3.2: __end__ nodes must not produce progress events."""

    def test_end_node_skipped(self):
        async def _run():
            chunks = [
                {"validate": {"x": 1}},
                {"__end__": {}},
                {"retrieve": {"y": 2}},
            ]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            result = await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="test",
                repo_id="repo1",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            # Two progress events (validate, retrieve) — no __end__
            assert mgr.send_event.call_count == 2
            nodes_sent = [
                call.kwargs["data"]["node"] for call in mgr.send_event.call_args_list
            ]
            assert "__end__" not in nodes_sent
            assert nodes_sent == ["validate", "retrieve"]
            # Final state accumulated from non-__end__ chunks
            assert result == {"x": 1, "y": 2}

        asyncio.run(_run())

    def test_only_end_nodes_produces_no_events(self):
        async def _run():
            chunks = [{"__end__": {}}, {"__end__": {"a": 1}}]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            result = await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            mgr.send_event.assert_not_called()
            assert result == {}

        asyncio.run(_run())


class TestLinearWorkflowProgress:
    """Req 3.4: linear workflows compute progress_percent correctly."""

    def test_progress_percent_linear(self):
        async def _run():
            chunks = [
                {"validate": {"s": 1}},
                {"retrieve": {"s": 2}},
                {"agent": {"s": 3}},
                {"format": {"s": 4}},
            ]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            assert mgr.send_event.call_count == 4
            percents = [
                call.kwargs["data"]["progress_percent"]
                for call in mgr.send_event.call_args_list
            ]
            total = len(NODE_PHASES)  # 4
            expected = [min((i / total) * 100, 100) for i in range(1, total + 1)]
            assert percents == expected

        asyncio.run(_run())

    def test_progress_capped_at_100(self):
        """If nodes_completed exceeds total_nodes, cap at 100."""

        async def _run():
            # Simulate more chunks than nodes in the map (e.g. unknown node)
            small_map = {"a": "phase_a"}
            chunks = [
                {"a": {"v": 1}},
                {"b": {"v": 2}},  # not in map, but still counted
                {"c": {"v": 3}},
            ]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=small_map,
                has_cycles=False,
            )

            percents = [
                call.kwargs["data"]["progress_percent"]
                for call in mgr.send_event.call_args_list
            ]
            # 1/1*100=100, 2/1*100=200→capped 100, 3/1*100=300→capped 100
            assert percents == [100.0, 100.0, 100.0]

        asyncio.run(_run())

    def test_total_nodes_equals_map_length(self):
        async def _run():
            chunks = [{"validate": {"v": 1}}]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            data = mgr.send_event.call_args_list[0].kwargs["data"]
            assert data["total_nodes"] == len(NODE_PHASES)

        asyncio.run(_run())


class TestCyclicWorkflowProgress:
    """Req 3.3: cyclic workflows use indeterminate progress."""

    def test_cyclic_progress_indeterminate(self):
        async def _run():
            chunks = [
                {"validate": {"s": 1}},
                {"agent": {"s": 2}},
                {"agent": {"s": 3}},  # revisited due to cycle
            ]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=True,
            )

            assert mgr.send_event.call_count == 3
            for call in mgr.send_event.call_args_list:
                data = call.kwargs["data"]
                assert data["progress_percent"] == -1
                assert data["total_nodes"] == -1

        asyncio.run(_run())


class TestProgressEventData:
    """Verify the shape and content of emitted progress events."""

    def test_event_data_shape(self):
        async def _run():
            chunks = [{"validate": {"result": "ok"}}]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            call_kwargs = mgr.send_event.call_args_list[0].kwargs
            assert call_kwargs["client_id"] == "c1"
            assert call_kwargs["event_type"] == "progress"
            assert call_kwargs["workflow_id"] == "wf1"

            data = call_kwargs["data"]
            assert data["phase"] == "validating"
            assert data["step"] == "validating"  # backward compat
            assert data["node"] == "validate"
            assert data["nodes_completed"] == 1
            assert data["message"] == "validating..."

        asyncio.run(_run())

    def test_unknown_node_uses_node_name_as_phase(self):
        async def _run():
            chunks = [{"unknown_node": {"v": 1}}]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            data = mgr.send_event.call_args_list[0].kwargs["data"]
            assert data["phase"] == "unknown_node"
            assert data["step"] == "unknown_node"

        asyncio.run(_run())

    def test_final_state_accumulated(self):
        async def _run():
            chunks = [
                {"validate": {"a": 1, "b": 2}},
                {"retrieve": {"c": 3}},
                {"agent": {"a": 99}},  # overwrites a
            ]
            engine = _make_engine(chunks)
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            result = await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            assert result == {"a": 99, "b": 2, "c": 3}

        asyncio.run(_run())

    def test_empty_stream_returns_empty_state(self):
        async def _run():
            engine = _make_engine([])
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            result = await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
            )

            mgr.send_event.assert_not_called()
            assert result == {}

        asyncio.run(_run())

    def test_kwargs_forwarded_to_engine(self):
        """Extra kwargs are passed through to start_workflow_stream."""

        async def _run():
            engine = MagicMock()
            captured_kwargs = {}

            async def _stream(**kwargs):
                captured_kwargs.update(kwargs)
                return
                yield  # make it an async generator

            engine.start_workflow_stream = _stream
            mgr = AsyncMock()
            mgr.send_event = AsyncMock(return_value=True)

            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=mgr,
                query="q",
                repo_id="r",
                node_phase_map=NODE_PHASES,
                has_cycles=False,
                custom_param="hello",
            )

            assert captured_kwargs["user_query"] == "q"
            assert captured_kwargs["user_id"] == "c1"
            assert captured_kwargs["session_id"] == "wf1"
            assert captured_kwargs["repo_id"] == "r"
            assert captured_kwargs["custom_param"] == "hello"

        asyncio.run(_run())
