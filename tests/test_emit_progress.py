"""Property-based test for _emit_progress() exception swallowing.

Feature: plan-feature-refactoring, Property 5: _emit_progress() swallows all
callback exceptions

**Validates: Requirements 5.2**
"""

from __future__ import annotations

from typing import Any

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

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


def _make_ctx(*, progress_cb=None, session_id: str = "sess-1") -> NodeContext:
    """Build a minimal NodeContext for testing _emit_progress."""
    return NodeContext(
        services={},
        session_id=session_id,
        budget={},
        phase="test",
        config={},
        configurable={},
        llm=None,
        artifact_service=None,
        workflow_context=None,
        client_id=None,
        progress_cb=progress_cb,
        db_session_factory=None,
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Exception types that a progress callback might raise
_exception_types_st = st.sampled_from([
    ValueError,
    TypeError,
    RuntimeError,
    ConnectionError,
    OSError,
    KeyError,
    IndexError,
    AttributeError,
    IOError,
    PermissionError,
    TimeoutError,
    OverflowError,
    StopIteration,
    UnicodeError,
    ArithmeticError,
    LookupError,
    MemoryError,
    NotImplementedError,
    Exception,
])

_step_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=50,
)

_progress_pct_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)

_message_st = st.text(min_size=0, max_size=200)

_phase_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

_session_id_st = st.text(min_size=0, max_size=50)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestEmitProgressExceptionSwallowingProperty:
    """Feature: plan-feature-refactoring, Property 5: _emit_progress() swallows
    all callback exceptions

    For any exception type raised by the progress callback function, calling
    _emit_progress() should not propagate the exception and should return
    normally (None).

    **Validates: Requirements 5.2**
    """

    @given(
        exc_type=_exception_types_st,
        step_name=_step_name_st,
        progress_pct=_progress_pct_st,
        message=_message_st,
        phase=_phase_st,
        session_id=_session_id_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    async def test_swallows_all_exception_types(
        self,
        exc_type: type,
        step_name: str,
        progress_pct: float,
        message: str,
        phase: str,
        session_id: str,
    ):
        """_emit_progress() catches any exception from the callback and returns None.

        Feature: plan-feature-refactoring, Property 5: _emit_progress() swallows all callback exceptions

        **Validates: Requirements 5.2**
        """

        async def failing_cb(data: dict[str, Any]) -> None:
            raise exc_type(f"simulated {exc_type.__name__}")

        node = _TestNode(phase=phase)
        ctx = _make_ctx(progress_cb=failing_cb, session_id=session_id)

        # Must not propagate — should return None
        result = await node._emit_progress(ctx, step_name, progress_pct, message)
        assert result is None

    @given(
        exc_type=_exception_types_st,
        exc_msg=st.text(min_size=0, max_size=100),
        step_name=_step_name_st,
        progress_pct=_progress_pct_st,
        message=_message_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    async def test_swallows_exceptions_with_arbitrary_messages(
        self,
        exc_type: type,
        exc_msg: str,
        step_name: str,
        progress_pct: float,
        message: str,
    ):
        """Exception message content does not affect swallowing behavior.

        Feature: plan-feature-refactoring, Property 5: _emit_progress() swallows all callback exceptions

        **Validates: Requirements 5.2**
        """

        async def failing_cb(data: dict[str, Any]) -> None:
            raise exc_type(exc_msg)

        node = _TestNode(phase="research")
        ctx = _make_ctx(progress_cb=failing_cb)

        result = await node._emit_progress(ctx, step_name, progress_pct, message)
        assert result is None
