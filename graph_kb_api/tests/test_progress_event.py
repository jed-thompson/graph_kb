"""
Tests for ProgressEvent dataclass and to_send_data() method.

Validates Requirements 6.1, 6.2, 6.3.
"""

import pytest

from graph_kb_api.websocket.progress import ProgressEvent


class TestProgressEventCreation:
    """Test ProgressEvent construction and validation."""

    def test_basic_creation(self):
        event = ProgressEvent(phase="cloning", message="Cloning repo...")
        assert event.phase == "cloning"
        assert event.message == "Cloning repo..."
        assert event.progress_percent == -1
        assert event.detail is None

    def test_with_all_fields(self):
        detail = {"repo_id": "abc", "total_files": 42}
        event = ProgressEvent(
            phase="indexing",
            message="Indexing files...",
            progress_percent=55.5,
            detail=detail,
        )
        assert event.phase == "indexing"
        assert event.progress_percent == 55.5
        assert event.detail == detail

    def test_empty_phase_raises(self):
        with pytest.raises(ValueError, match="phase must be a non-empty string"):
            ProgressEvent(phase="", message="hello")

    def test_empty_message_raises(self):
        with pytest.raises(ValueError, match="message must be a non-empty string"):
            ProgressEvent(phase="init", message="")

    def test_percent_below_range_raises(self):
        with pytest.raises(ValueError, match="progress_percent"):
            ProgressEvent(phase="x", message="y", progress_percent=-2)

    def test_percent_above_range_raises(self):
        with pytest.raises(ValueError, match="progress_percent"):
            ProgressEvent(phase="x", message="y", progress_percent=101)

    def test_percent_zero_valid(self):
        event = ProgressEvent(phase="x", message="y", progress_percent=0)
        assert event.progress_percent == 0

    def test_percent_hundred_valid(self):
        event = ProgressEvent(phase="x", message="y", progress_percent=100)
        assert event.progress_percent == 100

    def test_percent_negative_one_valid(self):
        event = ProgressEvent(phase="x", message="y", progress_percent=-1)
        assert event.progress_percent == -1


class TestToSendData:
    """Test to_send_data() output shape. Validates Req 6.1, 6.2, 6.3."""

    def test_contains_phase_and_step(self):
        """Req 6.1: result must contain both phase and step with equal values."""
        event = ProgressEvent(phase="reasoning", message="Thinking...")
        data = event.to_send_data()
        assert data["phase"] == "reasoning"
        assert data["step"] == "reasoning"
        assert data["phase"] == data["step"]

    def test_contains_progress_percent(self):
        """Req 6.2: progress_percent present in output."""
        event = ProgressEvent(phase="a", message="b", progress_percent=42.0)
        data = event.to_send_data()
        assert data["progress_percent"] == 42.0

    def test_indeterminate_percent(self):
        event = ProgressEvent(phase="a", message="b")
        data = event.to_send_data()
        assert data["progress_percent"] == -1

    def test_message_in_output(self):
        event = ProgressEvent(phase="a", message="Working hard")
        data = event.to_send_data()
        assert data["message"] == "Working hard"

    def test_detail_merged_into_result(self):
        """Req 6.3: detail fields merged into top-level result."""
        detail = {"repo_id": "r1", "total_files": 10, "processed_files": 3}
        event = ProgressEvent(phase="indexing", message="Indexing...", detail=detail)
        data = event.to_send_data()
        assert data["repo_id"] == "r1"
        assert data["total_files"] == 10
        assert data["processed_files"] == 3
        # Core keys still present
        assert data["phase"] == "indexing"
        assert data["step"] == "indexing"

    def test_no_detail_no_extra_keys(self):
        event = ProgressEvent(phase="a", message="b")
        data = event.to_send_data()
        assert set(data.keys()) == {"phase", "step", "progress_percent", "message"}

    def test_langgraph_detail(self):
        """Req 6.3: LangGraph-specific detail fields merged."""
        detail = {"node": "retrieve", "nodes_completed": 3, "total_nodes": 9}
        event = ProgressEvent(
            phase="retrieving",
            message="Retrieving...",
            progress_percent=33.3,
            detail=detail,
        )
        data = event.to_send_data()
        assert data["node"] == "retrieve"
        assert data["nodes_completed"] == 3
        assert data["total_nodes"] == 9


import asyncio
import threading

from graph_kb_api.websocket.progress import ThreadSafeBridge


class TestThreadSafeBridge:
    """Tests for ThreadSafeBridge. Validates Requirements 4.1, 4.2."""

    def test_send_enqueues_event_on_running_loop(self):
        """Req 4.2: event appears in the queue when the loop is running."""

        async def _run():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            bridge = ThreadSafeBridge(loop, queue)

            event = {"phase": "cloning", "message": "hello"}
            # Call send from a worker thread
            done = threading.Event()

            def worker():
                bridge.send(event)
                done.set()

            t = threading.Thread(target=worker)
            t.start()
            done.wait(timeout=2)
            t.join(timeout=2)

            # Give the loop a moment to process the call_soon_threadsafe callback
            await asyncio.sleep(0.05)

            assert not queue.empty()
            assert queue.get_nowait() == event

        asyncio.run(_run())

    def test_send_with_closed_loop_does_not_raise(self):
        """Req 4.1: RuntimeError is caught when the event loop is closed."""
        loop = asyncio.new_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        bridge = ThreadSafeBridge(loop, queue)
        loop.close()

        # Should not raise
        bridge.send({"phase": "test", "message": "dropped"})

    def test_send_does_not_block_caller(self):
        """Req 4.2: send returns without blocking the calling thread."""

        async def _run():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            bridge = ThreadSafeBridge(loop, queue)

            completed = threading.Event()

            def worker():
                bridge.send({"phase": "a", "message": "b"})
                completed.set()

            t = threading.Thread(target=worker)
            t.start()
            # If send blocked, this would time out
            assert completed.wait(timeout=2), "send() blocked the calling thread"
            t.join(timeout=2)

        asyncio.run(_run())

    def test_multiple_sends_from_thread(self):
        """Multiple events sent from a thread all arrive in the queue."""

        async def _run():
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue = asyncio.Queue()
            bridge = ThreadSafeBridge(loop, queue)

            events = [{"i": i} for i in range(5)]
            done = threading.Event()

            def worker():
                for e in events:
                    bridge.send(e)
                done.set()

            t = threading.Thread(target=worker)
            t.start()
            done.wait(timeout=2)
            t.join(timeout=2)

            await asyncio.sleep(0.05)

            received = []
            while not queue.empty():
                received.append(queue.get_nowait())
            assert received == events

        asyncio.run(_run())


from unittest.mock import AsyncMock

from graph_kb_api.websocket.progress import consume_progress_queue


class TestConsumeProgressQueue:
    """Tests for consume_progress_queue(). Validates Requirements 8.1, 8.2."""

    def test_sends_all_events_then_stops_on_sentinel(self):
        """Req 8.1: N events followed by None sentinel → exactly N send_event calls."""

        async def _run():
            queue: asyncio.Queue = asyncio.Queue()
            manager = AsyncMock()
            manager.send_event = AsyncMock(return_value=True)

            events = [
                {"phase": "cloning", "message": "step 1"},
                {"phase": "indexing", "message": "step 2"},
                {"phase": "embedding", "message": "step 3"},
            ]
            for e in events:
                queue.put_nowait(e)
            queue.put_nowait(None)  # sentinel

            await consume_progress_queue(
                queue=queue,
                client_id="client-1",
                workflow_id="wf-1",
                manager=manager,
            )

            assert manager.send_event.call_count == 3
            for i, call in enumerate(manager.send_event.call_args_list):
                assert call.kwargs["client_id"] == "client-1"
                assert call.kwargs["event_type"] == "progress"
                assert call.kwargs["workflow_id"] == "wf-1"
                assert call.kwargs["data"] == events[i]

        asyncio.run(_run())

    def test_fifo_order_preserved(self):
        """Req 8.2: events are sent in the same FIFO order they were enqueued."""

        async def _run():
            queue: asyncio.Queue = asyncio.Queue()
            manager = AsyncMock()
            sent_data = []

            async def capture_send(**kwargs):
                sent_data.append(kwargs["data"])
                return True

            manager.send_event = AsyncMock(side_effect=capture_send)

            for i in range(5):
                queue.put_nowait({"order": i})
            queue.put_nowait(None)

            await consume_progress_queue(
                queue=queue,
                client_id="c",
                workflow_id="w",
                manager=manager,
            )

            assert sent_data == [{"order": i} for i in range(5)]

        asyncio.run(_run())

    def test_immediate_sentinel_sends_nothing(self):
        """Edge case: sentinel with no preceding events → zero send_event calls."""

        async def _run():
            queue: asyncio.Queue = asyncio.Queue()
            manager = AsyncMock()
            manager.send_event = AsyncMock(return_value=True)

            queue.put_nowait(None)

            await consume_progress_queue(
                queue=queue,
                client_id="c",
                workflow_id="w",
                manager=manager,
            )

            manager.send_event.assert_not_called()

        asyncio.run(_run())

    def test_continues_when_send_event_returns_false(self):
        """Consumer keeps going even if send_event returns False (client disconnected)."""

        async def _run():
            queue: asyncio.Queue = asyncio.Queue()
            manager = AsyncMock()
            manager.send_event = AsyncMock(return_value=False)

            queue.put_nowait({"phase": "a", "message": "1"})
            queue.put_nowait({"phase": "b", "message": "2"})
            queue.put_nowait(None)

            await consume_progress_queue(
                queue=queue,
                client_id="c",
                workflow_id="w",
                manager=manager,
            )

            assert manager.send_event.call_count == 2

        asyncio.run(_run())
