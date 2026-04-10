"""Property-based tests for _unpack() and NodeContext.

Feature: plan-feature-refactoring, Property 4: _unpack() returns correct NodeContext
with graceful defaults

**Validates: Requirements 4.2, 4.4, 14.3**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

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
# Strategies
# ---------------------------------------------------------------------------

# Arbitrary JSON-safe values for state/config fields
_json_value_st = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)

_budget_st = st.fixed_dictionaries(
    {},
    optional={
        "remaining_llm_calls": st.integers(min_value=0, max_value=100),
        "tokens_used": st.integers(min_value=0, max_value=100000),
        "max_llm_calls": st.integers(min_value=1, max_value=200),
    },
)


@st.composite
def state_dict_st(draw):
    """Generate a random state dict with optional session_id and budget fields."""
    result: dict[str, Any] = {}

    # Randomly include or omit session_id
    include_session = draw(st.booleans())
    if include_session:
        result["session_id"] = draw(st.text(min_size=0, max_size=30))

    # Randomly include or omit budget
    include_budget = draw(st.booleans())
    if include_budget:
        result["budget"] = draw(_budget_st)

    # Add some extra state keys (nodes may have other state fields)
    extras = draw(st.dictionaries(
        keys=st.text(min_size=1, max_size=15).filter(
            lambda k: k not in ("session_id", "budget")
        ),
        values=_json_value_st,
        max_size=4,
    ))
    result.update(extras)

    return result


@st.composite
def config_dict_st(draw):
    """Generate a random RunnableConfig dict with optional configurable fields.

    Uses MagicMock for service objects (llm, artifact_service, workflow_context).
    """
    configurable: dict[str, Any] = {}

    # Randomly include or omit each optional configurable field
    if draw(st.booleans()):
        configurable["llm"] = MagicMock(name="llm")

    if draw(st.booleans()):
        configurable["artifact_service"] = MagicMock(name="artifact_service")

    if draw(st.booleans()):
        configurable["client_id"] = draw(st.text(min_size=0, max_size=20))

    if draw(st.booleans()):
        configurable["progress_callback"] = MagicMock(name="progress_callback")

    if draw(st.booleans()):
        configurable["services"] = {"svc": MagicMock(name="svc")}
    
    # workflow_context: randomly None, present without app_context, or present with app_context
    wf_choice = draw(st.sampled_from(["absent", "no_app_ctx", "app_ctx_none", "app_ctx_present"]))
    if wf_choice == "no_app_ctx":
        wf = MagicMock(spec=[])  # no attributes at all
        configurable["context"] = wf
    elif wf_choice == "app_ctx_none":
        wf = MagicMock()
        wf.app_context = None
        configurable["context"] = wf
    elif wf_choice == "app_ctx_present":
        wf = MagicMock()
        wf.app_context = MagicMock(name="app_context")
        configurable["context"] = wf
    # "absent" — no workflow_context key

    config: dict[str, Any] = {"configurable": configurable}
    return config


_phase_st = st.sampled_from(["context", "research", "planning", "orchestrate", "assembly"])


# ---------------------------------------------------------------------------
# Property 4: _unpack() returns correct NodeContext with graceful defaults
# ---------------------------------------------------------------------------


class TestUnpackProperty:
    """Feature: plan-feature-refactoring, Property 4: _unpack() returns correct
    NodeContext with graceful defaults

    **Validates: Requirements 4.2, 4.4, 14.3**
    """

    @given(
        state=state_dict_st(),
        config=config_dict_st(),
        phase=_phase_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_present_fields_match_source_values(
        self, state: dict[str, Any], config: dict[str, Any], phase: str
    ):
        """When optional fields are present in state/config, the NodeContext
        fields match their source values exactly.

        Feature: plan-feature-refactoring, Property 4: _unpack() returns correct
        NodeContext with graceful defaults

        **Validates: Requirements 4.2, 4.4, 14.3**
        """
        node = _TestNode(phase=phase)
        ctx = node._unpack(state, config)
        configurable = config.get("configurable", {})

        # session_id: from state if present, else ""
        if "session_id" in state:
            assert ctx.session_id == state["session_id"], (
                f"session_id mismatch: expected {state['session_id']!r}, got {ctx.session_id!r}"
            )

        # budget: from state if present, else {}
        if "budget" in state:
            assert ctx.budget == state["budget"], (
                f"budget mismatch: expected {state['budget']!r}, got {ctx.budget!r}"
            )

        # phase always comes from the node
        assert ctx.phase == phase

        # config is passed through
        assert ctx.config is config

        # configurable matches
        assert ctx.configurable == configurable

        # llm: from configurable if present
        if "llm" in configurable:
            assert ctx.llm is configurable["llm"]

        # artifact_service: from configurable if present
        if "artifact_service" in configurable:
            assert ctx.artifact_service is configurable["artifact_service"]

        # client_id: from configurable if present
        if "client_id" in configurable:
            assert ctx.client_id == configurable["client_id"]

        # progress_cb: from configurable if present
        if "progress_callback" in configurable:
            assert ctx.progress_cb is configurable["progress_callback"]

        # services: from configurable if present
        if "services" in configurable:
            assert ctx.services == configurable["services"]

        # workflow_context: from configurable["context"] if present
        if "context" in configurable:
            assert ctx.workflow_context is configurable["context"]

    @given(
        state=state_dict_st(),
        config=config_dict_st(),
        phase=_phase_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_optional_fields_get_sensible_defaults(
        self, state: dict[str, Any], config: dict[str, Any], phase: str
    ):
        """When optional fields are missing from state/config, NodeContext
        provides sensible defaults: "" for session_id, {} for budget,
        None for optional services.

        Feature: plan-feature-refactoring, Property 4: _unpack() returns correct
        NodeContext with graceful defaults

        **Validates: Requirements 4.2, 4.4, 14.3**
        """
        node = _TestNode(phase=phase)
        ctx = node._unpack(state, config)
        configurable = config.get("configurable", {})

        # session_id defaults to ""
        if "session_id" not in state:
            assert ctx.session_id == "", (
                f"Missing session_id should default to '', got {ctx.session_id!r}"
            )

        # budget defaults to {}
        if "budget" not in state:
            assert ctx.budget == {}, (
                f"Missing budget should default to {{}}, got {ctx.budget!r}"
            )

        # llm defaults to None
        if "llm" not in configurable:
            assert ctx.llm is None, f"Missing llm should default to None, got {ctx.llm!r}"

        # artifact_service defaults to None
        if "artifact_service" not in configurable:
            assert ctx.artifact_service is None

        # client_id defaults to None
        if "client_id" not in configurable:
            assert ctx.client_id is None

        # progress_cb defaults to None
        if "progress_callback" not in configurable:
            assert ctx.progress_cb is None

        # services defaults to {}
        if "services" not in configurable:
            assert ctx.services == {}

        # workflow_context defaults to None
        if "context" not in configurable:
            assert ctx.workflow_context is None

    @given(
        state=state_dict_st(),
        config=config_dict_st(),
        phase=_phase_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_db_session_factory_derived_from_workflow_context(
        self, state: dict[str, Any], config: dict[str, Any], phase: str
    ):
        """db_session_factory is derived from workflow_context.app_context when
        available, and is None otherwise.

        Feature: plan-feature-refactoring, Property 4: _unpack() returns correct
        NodeContext with graceful defaults

        **Validates: Requirements 4.2, 4.4, 14.3**
        """
        node = _TestNode(phase=phase)
        ctx = node._unpack(state, config)
        configurable = config.get("configurable", {})
        wf_ctx = configurable.get("context")

        if wf_ctx is None:
            # No workflow_context → db_session_factory must be None
            assert ctx.db_session_factory is None
        else:
            app_ctx = getattr(wf_ctx, "app_context", None)
            if app_ctx is not None:
                assert ctx.db_session_factory is app_ctx
            else:
                assert ctx.db_session_factory is None

    @given(
        state=state_dict_st(),
        config=config_dict_st(),
        phase=_phase_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_returns_frozen_node_context(
        self, state: dict[str, Any], config: dict[str, Any], phase: str
    ):
        """_unpack() always returns a NodeContext instance (frozen dataclass).

        Feature: plan-feature-refactoring, Property 4: _unpack() returns correct
        NodeContext with graceful defaults

        **Validates: Requirements 4.2, 4.4, 14.3**
        """
        node = _TestNode(phase=phase)
        ctx = node._unpack(state, config)

        assert isinstance(ctx, NodeContext), (
            f"Expected NodeContext instance, got {type(ctx).__name__}"
        )
