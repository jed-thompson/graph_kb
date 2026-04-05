"""Property-based tests for ProgressEvent using Hypothesis."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.websocket.progress import ProgressEvent, ThreadSafeBridge

# Strategy: generate valid ProgressEvent instances
# progress_percent is either -1 or a float in [0, 100]
valid_percent = st.one_of(
    st.just(-1.0),
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
)

valid_detail = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(st.integers(), st.text(max_size=50), st.booleans()),
        max_size=5,
    ),
)

progress_events = st.builds(
    ProgressEvent,
    phase=st.text(min_size=1, max_size=50),
    message=st.text(min_size=1, max_size=200),
    progress_percent=valid_percent,
    detail=valid_detail,
)


class TestPercentBoundsProperty:
    """**Validates: Requirements 6.2**"""

    @given(event=progress_events)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_to_send_data_percent_is_minus_one_or_in_range(
        self, event: ProgressEvent
    ) -> None:
        """Property 3: Percent Bounds

        For any valid ProgressEvent, to_send_data()["progress_percent"]
        is either -1 (indeterminate) or a float in [0, 100].

        **Validates: Requirements 6.2**
        """
        data = event.to_send_data()
        pct = data["progress_percent"]
        assert pct == -1 or (0 <= pct <= 100), (
            f"progress_percent {pct} is not -1 and not in [0, 100]"
        )


class TestThreadSafeBridgeThreadSafety:
    """Property 5: Thread Safety

    Spawn multiple threads calling bridge.send() concurrently, assert all
    events appear in the queue with no corruption.

    **Validates: Requirements 4.1, 4.2**
    """

    @given(
        event_lists=st.lists(
            st.lists(
                st.dictionaries(
                    keys=st.text(min_size=1, max_size=10),
                    values=st.one_of(
                        st.integers(min_value=-1000, max_value=1000),
                        st.text(max_size=30),
                        st.booleans(),
                    ),
                    min_size=1,
                    max_size=5,
                ),
                min_size=1,
                max_size=10,
            ),
            min_size=2,
            max_size=6,
        )
    )
    @settings(max_examples=100, deadline=5000)
    def test_all_events_arrive_without_corruption(
        self, event_lists: list[list[dict]]
    ) -> None:
        """For any number of concurrent bridge.send() calls from multiple
        threads, all events eventually appear in the queue with no corruption.

        **Validates: Requirements 4.1, 4.2**
        """
        import asyncio
        import threading

        async def _run() -> list[dict]:
            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[dict | None] = asyncio.Queue()
            bridge = ThreadSafeBridge(loop, queue)

            sum(len(evts) for evts in event_lists)

            def _sender(events: list[dict]) -> None:
                for evt in events:
                    bridge.send(evt)

            threads = [
                threading.Thread(target=_sender, args=(evts,)) for evts in event_lists
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Allow the event loop to process all call_soon_threadsafe callbacks
            await asyncio.sleep(0.05)

            collected: list[dict] = []
            while not queue.empty():
                collected.append(queue.get_nowait())

            return collected

        collected = asyncio.run(_run())

        # Flatten all expected events
        all_expected = [evt for evts in event_lists for evt in evts]

        # Every event must appear (count-based, order across threads is non-deterministic)
        assert len(collected) == len(all_expected), (
            f"Expected {len(all_expected)} events, got {len(collected)}"
        )

        # Verify no corruption: each collected event must equal one of the sent events
        # Use a mutable copy to handle duplicates correctly
        remaining = list(all_expected)
        for evt in collected:
            assert evt in remaining, f"Corrupted or unexpected event in queue: {evt}"
            remaining.remove(evt)


class TestNoEndLeakageProperty:
    """Property 9: No __end__ Leakage

    For any stream of chunks including ``__end__`` nodes,
    ``stream_workflow_with_progress`` never emits a progress event with
    ``node == "__end__"``.

    **Validates: Requirements 3.2**
    """

    # Strategy: generate a list of stream chunks.  Each chunk is a dict
    # mapping node names to state dicts.  Some node names are ``"__end__"``
    # to exercise the filtering logic.
    _node_names = st.one_of(
        st.just("__end__"),
        st.sampled_from(["validate", "retrieve", "agent", "format", "present"]),
    )

    _state_values = st.dictionaries(
        keys=st.text(min_size=1, max_size=10),
        values=st.one_of(st.integers(), st.text(max_size=20), st.booleans()),
        max_size=3,
    )

    _chunk = st.dictionaries(
        keys=_node_names,
        values=_state_values,
        min_size=1,
        max_size=3,
    )

    _chunks = st.lists(_chunk, min_size=0, max_size=15)

    @given(chunks=_chunks)
    @settings(max_examples=200, deadline=5000)
    def test_no_end_node_in_progress_events(self, chunks: list[dict]) -> None:
        """For any sequence of stream chunks (including ``__end__`` entries),
        no progress event emitted by ``stream_workflow_with_progress`` has
        ``node == "__end__"``.

        **Validates: Requirements 3.2**
        """
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from graph_kb_api.websocket.progress import stream_workflow_with_progress

        node_phase_map = {
            "validate": "validating",
            "retrieve": "retrieving",
            "agent": "reasoning",
            "format": "formatting",
            "present": "presenting",
        }

        # Build a mock engine whose start_workflow_stream yields the chunks
        engine = MagicMock()

        async def _stream(**kwargs):
            for c in chunks:
                yield c

        engine.start_workflow_stream = _stream

        manager = AsyncMock()
        manager.send_event = AsyncMock(return_value=True)

        async def _run():
            await stream_workflow_with_progress(
                engine=engine,
                client_id="c1",
                workflow_id="wf1",
                manager=manager,
                query="test",
                repo_id="repo1",
                node_phase_map=node_phase_map,
                has_cycles=False,
            )

        asyncio.run(_run())

        # Assert: no emitted progress event has node == "__end__"
        for call in manager.send_event.call_args_list:
            data = (
                call.kwargs.get("data") or call.args[3]
                if len(call.args) > 3
                else call.kwargs.get("data", {})
            )
            assert data.get("node") != "__end__", (
                f"Progress event leaked __end__ node: {data}"
            )


class TestEventOrderingProperty:
    """Property 2: Event Ordering

    For any sequence of N progress events enqueued, the consumer sends
    exactly N events in FIFO order before terminating on sentinel.

    **Validates: Requirements 8.1, 8.2**
    """

    # Strategy: generate a list of event dicts (simulating progress payloads)
    _event_dicts = st.lists(
        st.dictionaries(
            keys=st.sampled_from(
                ["phase", "step", "progress_percent", "message", "node"]
            ),
            values=st.one_of(
                st.integers(min_value=-1, max_value=100),
                st.text(min_size=1, max_size=30),
                st.booleans(),
            ),
            min_size=1,
            max_size=5,
        ),
        min_size=0,
        max_size=20,
    )

    @given(events=_event_dicts)
    @settings(max_examples=200, deadline=5000)
    def test_consumer_sends_n_events_in_fifo_order(self, events: list[dict]) -> None:
        """For any sequence of N progress events followed by a None sentinel,
        consume_progress_queue calls send_event exactly N times and the
        events arrive in the same FIFO order they were enqueued.

        **Validates: Requirements 8.1, 8.2**
        """
        import asyncio
        from unittest.mock import AsyncMock

        from graph_kb_api.websocket.progress import consume_progress_queue

        async def _run() -> None:
            queue: asyncio.Queue = asyncio.Queue()

            # Enqueue all events followed by the None sentinel
            for evt in events:
                queue.put_nowait(evt)
            queue.put_nowait(None)

            manager = AsyncMock()
            manager.send_event = AsyncMock(return_value=True)

            await consume_progress_queue(
                queue=queue,
                client_id="c1",
                workflow_id="wf1",
                manager=manager,
            )

            # 1. send_event was called exactly N times
            assert manager.send_event.call_count == len(events), (
                f"Expected {len(events)} send_event calls, "
                f"got {manager.send_event.call_count}"
            )

            # 2. Events were sent in FIFO order
            for i, call in enumerate(manager.send_event.call_args_list):
                sent_data = call.kwargs.get("data")
                assert sent_data == events[i], (
                    f"Event at index {i} mismatch: "
                    f"expected {events[i]}, got {sent_data}"
                )

        asyncio.run(_run())
