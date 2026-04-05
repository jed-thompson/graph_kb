"""
Unit tests for the WebSocket progress system.

Tests ThreadSafeBridge, consume_progress_queue, and ProgressEvent
to diagnose the silent failure issue in /ingest workflows.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from graph_kb_api.websocket.progress import (
    ProgressEvent,
    ThreadSafeBridge,
    consume_progress_queue,
)


class TestProgressEvent:
    """Tests for ProgressEvent dataclass."""

    def test_valid_progress_event(self):
        """Test creating a valid progress event."""
        event = ProgressEvent(
            phase="cloning",
            message="Cloning repository...",
            progress_percent=50.0,
        )
        assert event.phase == "cloning"
        assert event.message == "Cloning repository..."
        assert event.progress_percent == 50.0
        assert event.detail is None

    def test_progress_event_with_detail(self):
        """Test progress event with detail dict."""
        event = ProgressEvent(
            phase="indexing",
            message="Indexing files",
            progress_percent=25.0,
            detail={"files_processed": 10, "total_files": 40},
        )
        assert event.detail["files_processed"] == 10

    def test_progress_event_indeterminate(self):
        """Test progress event with indeterminate progress (-1)."""
        event = ProgressEvent(
            phase="initializing",
            message="Starting...",
            progress_percent=-1,
        )
        assert event.progress_percent == -1

    def test_progress_event_invalid_phase(self):
        """Test that empty phase raises ValueError."""
        with pytest.raises(ValueError, match="phase must be a non-empty string"):
            ProgressEvent(phase="", message="test")

    def test_progress_event_invalid_message(self):
        """Test that empty message raises ValueError."""
        with pytest.raises(ValueError, match="message must be a non-empty string"):
            ProgressEvent(phase="test", message="")

    def test_progress_event_invalid_percent(self):
        """Test that invalid progress_percent raises ValueError."""
        with pytest.raises(ValueError, match="progress_percent must be"):
            ProgressEvent(phase="test", message="test", progress_percent=150)

    def test_to_send_data(self):
        """Test conversion to send data dict."""
        event = ProgressEvent(
            phase="embedding",
            message="Generating embeddings",
            progress_percent=75.0,
            detail={"chunks": 100},
        )
        data = event.to_send_data()
        assert data["phase"] == "embedding"
        assert data["step"] == "embedding"  # backward compat
        assert data["progress_percent"] == 75.0
        assert data["message"] == "Generating embeddings"
        assert data["chunks"] == 100


class TestThreadSafeBridge:
    """Tests for ThreadSafeBridge class."""

    def test_init(self):
        """Test bridge initialization."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        try:
            bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf-123")
            assert bridge.loop is loop
            assert bridge.queue is queue
            assert bridge.workflow_id == "test-wf-123"
            assert bridge._events_sent == 0
            assert bridge._events_dropped == 0
        finally:
            loop.close()

    def test_send_success(self):
        """Test successful event sending."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        try:
            bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")
            event = {"phase": "cloning", "message": "test"}

            bridge.send(event)

            # Check that event was queued (need to run in loop)
            def check_queue():
                return queue.qsize()

            loop.run_until_complete(loop.run_in_executor(None, check_queue))
            # The event should have been put in the queue via call_soon_threadsafe
            assert bridge._events_sent == 1
            assert bridge._events_dropped == 0
        finally:
            loop.close()

    def test_send_runtime_error_logged(self):
        """Test that RuntimeError (closed event loop) is logged, not raised."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        loop.close()  # Close the loop to trigger RuntimeError

        bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")
        event = {"phase": "cloning", "message": "test"}

        # Should not raise, should log warning
        bridge.send(event)

        # Event should be counted as dropped
        assert bridge._events_dropped >= 1

    def test_get_stats(self):
        """Test statistics retrieval."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        try:
            bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")
            bridge._events_sent = 10
            bridge._events_dropped = 2

            stats = bridge.get_stats()

            assert stats["events_sent"] == 10
            assert stats["events_dropped"] == 2
            assert "queue_size" in stats
        finally:
            loop.close()

    def test_send_multiple_events(self):
        """Test sending multiple events in sequence."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        try:
            bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")

            for i in range(5):
                bridge.send({"phase": "test", "index": i})

            assert bridge._events_sent == 5
            assert bridge._events_dropped == 0
        finally:
            loop.close()


class TestConsumeProgressQueue:
    """Tests for consume_progress_queue async function."""

    @pytest.mark.asyncio
    async def test_consume_single_event(self):
        """Test consuming a single event from the queue."""
        queue = asyncio.Queue()
        manager = MagicMock()
        manager.send_event = AsyncMock(return_value=True)

        await queue.put({"phase": "test", "message": "test event"})
        await queue.put(None)  # sentinel

        await consume_progress_queue(
            queue=queue,
            client_id="client-1",
            workflow_id="wf-1",
            manager=manager,
        )

        manager.send_event.assert_called_once()
        call_args = manager.send_event.call_args
        assert call_args.kwargs["client_id"] == "client-1"
        assert call_args.kwargs["workflow_id"] == "wf-1"
        assert call_args.kwargs["event_type"] == "progress"

    @pytest.mark.asyncio
    async def test_consume_multiple_events(self):
        """Test consuming multiple events."""
        queue = asyncio.Queue()
        manager = MagicMock()
        manager.send_event = AsyncMock(return_value=True)

        for i in range(3):
            await queue.put({"phase": f"phase-{i}", "message": f"msg-{i}"})
        await queue.put(None)  # sentinel

        await consume_progress_queue(
            queue=queue,
            client_id="client-1",
            workflow_id="wf-1",
            manager=manager,
        )

        assert manager.send_event.call_count == 3

    @pytest.mark.asyncio
    async def test_consume_handles_send_failure(self):
        """Test that send failures are logged but don't stop consumption."""
        queue = asyncio.Queue()
        manager = MagicMock()
        manager.send_event = AsyncMock(return_value=False)  # Simulate failure

        await queue.put({"phase": "test1", "message": "test1"})
        await queue.put({"phase": "test2", "message": "test2"})
        await queue.put(None)  # sentinel

        await consume_progress_queue(
            queue=queue,
            client_id="client-1",
            workflow_id="wf-1",
            manager=manager,
        )

        # Should have attempted both events despite failures
        assert manager.send_event.call_count == 2

    @pytest.mark.asyncio
    async def test_consume_handles_exception(self):
        """Test that exceptions in send_event don't crash the consumer."""
        queue = asyncio.Queue()
        manager = MagicMock()
        manager.send_event = AsyncMock(side_effect=Exception("Network error"))

        await queue.put({"phase": "test1", "message": "test1"})
        await queue.put({"phase": "test2", "message": "test2"})
        await queue.put(None)  # sentinel

        # Should not raise
        await consume_progress_queue(
            queue=queue,
            client_id="client-1",
            workflow_id="wf-1",
            manager=manager,
        )

        # Should have attempted both events
        assert manager.send_event.call_count == 2


class TestThreadSafeBridgeIntegration:
    """Integration tests for ThreadSafeBridge with consume_progress_queue."""

    @pytest.mark.asyncio
    async def test_bridge_to_consumer_flow(self):
        """Test the full flow from bridge.send() to consumer."""
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")

        manager = MagicMock()
        manager.send_event = AsyncMock(return_value=True)

        # Start consumer
        consumer_task = asyncio.create_task(
            consume_progress_queue(
                queue=queue,
                client_id="client-1",
                workflow_id="test-wf",
                manager=manager,
            )
        )

        # Send events via bridge
        bridge.send({"phase": "cloning", "message": "Starting clone"})
        bridge.send({"phase": "cloning", "message": "Clone progress", "progress_percent": 50})
        bridge.send({"phase": "indexing", "message": "Starting index"})

        # Give time for events to be processed
        await asyncio.sleep(0.1)

        # Send sentinel to stop consumer
        queue.put_nowait(None)
        await consumer_task

        # Verify all events were sent
        assert manager.send_event.call_count == 3
        assert bridge._events_sent == 3
        assert bridge._events_dropped == 0

    @pytest.mark.asyncio
    async def test_bridge_stats_after_workflow(self):
        """Test that bridge stats are accurate after workflow."""
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()
        bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")

        manager = MagicMock()
        manager.send_event = AsyncMock(return_value=True)

        consumer_task = asyncio.create_task(
            consume_progress_queue(
                queue=queue,
                client_id="client-1",
                workflow_id="test-wf",
                manager=manager,
            )
        )

        # Send 10 events
        for i in range(10):
            bridge.send({"phase": "test", "index": i})

        await asyncio.sleep(0.1)
        queue.put_nowait(None)
        await consumer_task

        stats = bridge.get_stats()
        assert stats["events_sent"] == 10
        assert stats["events_dropped"] == 0


class TestLoggingOutput:
    """Tests to verify logging output for debugging."""

    @pytest.mark.asyncio
    async def test_consumer_logs_start_and_stop(self, caplog):
        """Test that consumer logs its start and stop."""
        queue = asyncio.Queue()
        manager = MagicMock()
        manager.send_event = AsyncMock(return_value=True)

        with caplog.at_level(logging.INFO):
            await queue.put(None)  # immediate sentinel
            await consume_progress_queue(
                queue=queue,
                client_id="client-1",
                workflow_id="wf-1",
                manager=manager,
            )

        # Check for log messages
        log_messages = [r.message for r in caplog.records]
        assert any("Progress consumer started" in msg for msg in log_messages)
        assert any("Progress consumer finished" in msg for msg in log_messages)

    def test_bridge_logs_dropped_events(self, caplog):
        """Test that bridge logs when events are dropped due to closed loop."""
        loop = asyncio.new_event_loop()
        queue = asyncio.Queue()
        loop.close()

        bridge = ThreadSafeBridge(loop, queue, workflow_id="test-wf")

        with caplog.at_level(logging.WARNING):
            bridge.send({"phase": "test"})

        log_messages = [r.message for r in caplog.records]
        assert any("event dropped" in msg.lower() for msg in log_messages)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
