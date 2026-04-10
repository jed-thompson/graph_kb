"""Property-based tests for _decrement_budget helper on SubgraphAwareNode.

Tests that _decrement_budget correctly combines token counting and budget
decrement into a single call, preserving all other budget fields.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.services.budget_guard import BudgetGuard
from graph_kb_api.flows.v3.state.plan_state import BudgetState
from graph_kb_api.flows.v3.utils.token_estimation import get_token_estimator

# We need a concrete SubgraphAwareNode subclass since it's abstract.
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import SubgraphAwareNode
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from langgraph.types import RunnableConfig


class _StubNode(SubgraphAwareNode[Dict[str, Any]]):
    """Minimal concrete subclass for testing _decrement_budget."""

    phase = "test"
    step_name = "test_step"
    step_progress = 0.0

    def __init__(self):
        super().__init__(node_name="test_stub")

    async def _execute_step(self, state: Dict[str, Any], config: RunnableConfig) -> NodeExecutionResult:
        raise NotImplementedError("Not used in tests")


# --- Strategies ---

_ISO_TIMESTAMPS = st.just("2025-01-01T00:00:00+00:00")

_BUDGET_STATES = st.builds(
    lambda max_calls, remaining, max_tokens, tokens_used, max_wall, started_at: BudgetState(
        max_llm_calls=max_calls,
        remaining_llm_calls=remaining,
        max_tokens=max_tokens,
        tokens_used=tokens_used,
        max_wall_clock_s=max_wall,
        started_at=started_at,
    ),
    max_calls=st.integers(min_value=1, max_value=10000),
    remaining=st.integers(min_value=1, max_value=10000),
    max_tokens=st.integers(min_value=1000, max_value=10_000_000),
    tokens_used=st.integers(min_value=0, max_value=1_000_000),
    max_wall=st.integers(min_value=60, max_value=7200),
    started_at=_ISO_TIMESTAMPS,
)

_CONTENT_STRINGS = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=500,
)


class TestDecrementBudgetProperty:
    """Feature: plan-feature-refactoring, Property 16: _decrement_budget returns correctly decremented budget

    **Validates: Requirements 21.3**
    """

    @given(
        budget=_BUDGET_STATES,
        content=_CONTENT_STRINGS,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_remaining_llm_calls_decreased_by_n(
        self, budget: BudgetState, content: str, data: st.DataObject
    ):
        """remaining_llm_calls decreases by exactly llm_calls.

        Feature: plan-feature-refactoring, Property 16: _decrement_budget returns correctly decremented budget

        **Validates: Requirements 21.3**
        """
        llm_calls = data.draw(st.integers(min_value=1, max_value=budget["remaining_llm_calls"]))
        node = _StubNode()
        result = node._decrement_budget(budget, content, llm_calls=llm_calls)
        assert result["remaining_llm_calls"] == budget["remaining_llm_calls"] - llm_calls

    @given(
        budget=_BUDGET_STATES,
        content=_CONTENT_STRINGS,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_tokens_used_increased_by_token_count(
        self, budget: BudgetState, content: str, data: st.DataObject
    ):
        """tokens_used increases by exactly the token count of the content.

        Feature: plan-feature-refactoring, Property 16: _decrement_budget returns correctly decremented budget

        **Validates: Requirements 21.3**
        """
        llm_calls = data.draw(st.integers(min_value=1, max_value=budget["remaining_llm_calls"]))
        node = _StubNode()
        expected_tokens = get_token_estimator().count_tokens(content)
        result = node._decrement_budget(budget, content, llm_calls=llm_calls)
        assert result["tokens_used"] == budget["tokens_used"] + expected_tokens

    @given(
        budget=_BUDGET_STATES,
        content=_CONTENT_STRINGS,
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_other_budget_fields_unchanged(
        self, budget: BudgetState, content: str, data: st.DataObject
    ):
        """All budget fields except remaining_llm_calls and tokens_used are preserved.

        Feature: plan-feature-refactoring, Property 16: _decrement_budget returns correctly decremented budget

        **Validates: Requirements 21.3**
        """
        llm_calls = data.draw(st.integers(min_value=1, max_value=budget["remaining_llm_calls"]))
        node = _StubNode()
        result = node._decrement_budget(budget, content, llm_calls=llm_calls)

        # These fields must be unchanged
        assert result["max_llm_calls"] == budget["max_llm_calls"]
        assert result["max_tokens"] == budget["max_tokens"]
        assert result["max_wall_clock_s"] == budget["max_wall_clock_s"]
        assert result["started_at"] == budget["started_at"]

    @given(
        budget=_BUDGET_STATES,
        content_dict=st.dictionaries(
            keys=st.text(min_size=1, max_size=20),
            values=st.text(min_size=0, max_size=100),
            min_size=1,
            max_size=5,
        ),
        data=st.data(),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_dict_content_serialized_to_json(
        self, budget: BudgetState, content_dict: dict, data: st.DataObject
    ):
        """When content is a dict, it is serialized to JSON before token counting.

        Feature: plan-feature-refactoring, Property 16: _decrement_budget returns correctly decremented budget

        **Validates: Requirements 21.3**
        """
        llm_calls = data.draw(st.integers(min_value=1, max_value=budget["remaining_llm_calls"]))
        node = _StubNode()
        expected_text = json.dumps(content_dict, default=str)
        expected_tokens = get_token_estimator().count_tokens(expected_text)
        result = node._decrement_budget(budget, content_dict, llm_calls=llm_calls)
        assert result["tokens_used"] == budget["tokens_used"] + expected_tokens
