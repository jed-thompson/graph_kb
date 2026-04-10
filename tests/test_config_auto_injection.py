"""Property-based test for get_config_with_services() auto-injection.

Feature: plan-feature-refactoring, Property 12: get_config_with_services()
auto-injects all WorkflowContext attributes

**Validates: Requirements 14.5**
"""

from __future__ import annotations

import dataclasses
from typing import Any
from unittest.mock import MagicMock

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from graph_kb_api.flows.v3.graphs.base_workflow_engine import BaseWorkflowEngine
from graph_kb_api.flows.v3.services.workflow_context import WorkflowContext


# ---------------------------------------------------------------------------
# All field names on WorkflowContext (derived from the dataclass definition)
# ---------------------------------------------------------------------------

_WF_FIELD_NAMES = [f.name for f in dataclasses.fields(WorkflowContext)]


# ---------------------------------------------------------------------------
# Concrete test engine (BaseWorkflowEngine is abstract)
# ---------------------------------------------------------------------------


class _StubEngine(BaseWorkflowEngine):
    """Minimal concrete subclass that skips heavy graph compilation."""

    def __init__(self, workflow_context: WorkflowContext) -> None:
        # Bypass the real __init__ which calls require_llm, _initialize_tools,
        # _initialize_nodes, _compile_workflow, and CheckpointerFactory.
        # We only need self.workflow_context for get_config_with_services().
        self.workflow_context = workflow_context

    def _initialize_tools(self):
        return []

    def _initialize_nodes(self):
        pass

    def _compile_workflow(self):
        return MagicMock()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def workflow_context_st(draw):
    """Generate a WorkflowContext with a random subset of non-None fields.

    Each field is independently either None or a MagicMock sentinel,
    except ``llm`` which must be non-None (it doubles as require_llm).
    """
    kwargs: dict[str, Any] = {}
    for name in _WF_FIELD_NAMES:
        include = draw(st.booleans())
        if include:
            kwargs[name] = MagicMock(name=name)
        else:
            kwargs[name] = None
    return WorkflowContext(**kwargs)


_optional_config_st = st.one_of(
    st.none(),
    st.just({}),
    st.just({"configurable": {}}),
    # Config with pre-existing configurable keys that should be preserved
    st.fixed_dictionaries(
        {"configurable": st.dictionaries(
            keys=st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=15,
            ).filter(lambda k: k not in _WF_FIELD_NAMES and k != "context"),
            values=st.text(min_size=1, max_size=10),
            max_size=3,
        )},
    ),
)


# ---------------------------------------------------------------------------
# Property 12: get_config_with_services() auto-injects all WorkflowContext
# attributes
# ---------------------------------------------------------------------------


class TestConfigAutoInjectionProperty:
    """Feature: plan-feature-refactoring, Property 12: get_config_with_services()
    auto-injects all WorkflowContext attributes

    For any WorkflowContext instance with a random subset of non-None service
    attributes, calling get_config_with_services() should produce a config
    where config["configurable"] contains every non-None attribute from the
    WorkflowContext, and the "context" key maps to the WorkflowContext instance
    itself.

    **Validates: Requirements 14.5**
    """

    @given(wf_ctx=workflow_context_st(), input_config=_optional_config_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_non_none_fields_injected(
        self,
        wf_ctx: WorkflowContext,
        input_config: dict[str, Any] | None,
    ):
        """Every non-None WorkflowContext attribute appears in configurable.

        Feature: plan-feature-refactoring, Property 12: get_config_with_services()
        auto-injects all WorkflowContext attributes

        **Validates: Requirements 14.5**
        """
        engine = _StubEngine(wf_ctx)
        result = engine.get_config_with_services(input_config)

        configurable = result["configurable"]

        for f in dataclasses.fields(wf_ctx):
            value = getattr(wf_ctx, f.name)
            if value is not None:
                assert f.name in configurable, (
                    f"Non-None field '{f.name}' missing from configurable"
                )
                assert configurable[f.name] is value, (
                    f"Field '{f.name}' value mismatch in configurable"
                )

    @given(wf_ctx=workflow_context_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_none_fields_not_injected(
        self,
        wf_ctx: WorkflowContext,
    ):
        """None-valued WorkflowContext attributes are NOT injected into configurable.

        Uses a clean (empty) input config so that any field present in the
        result must have been injected by get_config_with_services itself.

        Feature: plan-feature-refactoring, Property 12: get_config_with_services()
        auto-injects all WorkflowContext attributes

        **Validates: Requirements 14.5**
        """
        engine = _StubEngine(wf_ctx)
        result = engine.get_config_with_services({})

        configurable = result["configurable"]

        for f in dataclasses.fields(wf_ctx):
            value = getattr(wf_ctx, f.name)
            if value is None:
                assert f.name not in configurable, (
                    f"None field '{f.name}' should not be in configurable"
                )

    @given(wf_ctx=workflow_context_st(), input_config=_optional_config_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_context_alias_maps_to_workflow_context(
        self,
        wf_ctx: WorkflowContext,
        input_config: dict[str, Any] | None,
    ):
        """The backward-compatible "context" key always maps to the WorkflowContext instance.

        Feature: plan-feature-refactoring, Property 12: get_config_with_services()
        auto-injects all WorkflowContext attributes

        **Validates: Requirements 14.5**
        """
        engine = _StubEngine(wf_ctx)
        result = engine.get_config_with_services(input_config)

        configurable = result["configurable"]

        assert "context" in configurable, (
            '"context" key must always be present in configurable'
        )
        assert configurable["context"] is wf_ctx, (
            '"context" must map to the WorkflowContext instance itself'
        )

    @given(wf_ctx=workflow_context_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_preexisting_config_keys_preserved(
        self,
        wf_ctx: WorkflowContext,
    ):
        """Pre-existing keys in configurable that don't collide with
        WorkflowContext fields are preserved after injection.

        Feature: plan-feature-refactoring, Property 12: get_config_with_services()
        auto-injects all WorkflowContext attributes

        **Validates: Requirements 14.5**
        """
        sentinel = object()
        input_config: dict[str, Any] = {
            "configurable": {"my_custom_key": sentinel},
        }

        engine = _StubEngine(wf_ctx)
        result = engine.get_config_with_services(input_config)

        assert result["configurable"]["my_custom_key"] is sentinel, (
            "Pre-existing configurable keys must be preserved"
        )
