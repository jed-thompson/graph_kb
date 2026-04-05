"""Property-based tests for BudgetGuard.

Properties 6–9 validate budget enforcement, purity, decrement correctness,
and monotonicity across randomly generated BudgetState values.
"""

import copy
from datetime import UTC, datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.services.budget_guard import (
    BudgetExhaustedError,
    BudgetGuard,
)
from graph_kb_api.flows.v3.state.plan_state import BudgetState

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def budget_state(draw: st.DrawFn) -> BudgetState:
    """Generate a random BudgetState with a recent started_at so wall-clock
    never triggers."""
    max_calls = draw(st.integers(min_value=1, max_value=1000))
    remaining = draw(st.integers(min_value=-10, max_value=max_calls))
    max_tokens = draw(st.integers(min_value=1, max_value=1_000_000))
    used = draw(st.integers(min_value=0, max_value=max_tokens + 100))
    max_wall = draw(st.integers(min_value=60, max_value=7200))
    started_at = datetime.now(UTC).isoformat()
    return BudgetState(
        max_llm_calls=max_calls,
        remaining_llm_calls=remaining,
        max_tokens=max_tokens,
        tokens_used=used,
        max_wall_clock_s=max_wall,
        started_at=started_at,
    )


@st.composite
def budget_state_with_capacity(draw: st.DrawFn) -> BudgetState:
    """Generate a BudgetState where all limits have remaining capacity."""
    max_calls = draw(st.integers(min_value=1, max_value=1000))
    remaining = draw(st.integers(min_value=1, max_value=max_calls))
    max_tokens = draw(st.integers(min_value=2, max_value=1_000_000))
    used = draw(st.integers(min_value=0, max_value=max_tokens - 1))
    max_wall = draw(st.integers(min_value=60, max_value=7200))
    started_at = datetime.now(UTC).isoformat()
    return BudgetState(
        max_llm_calls=max_calls,
        remaining_llm_calls=remaining,
        max_tokens=max_tokens,
        tokens_used=used,
        max_wall_clock_s=max_wall,
        started_at=started_at,
    )


@st.composite
def budget_state_exhausted_calls(draw: st.DrawFn) -> BudgetState:
    """Generate a BudgetState where remaining_llm_calls <= 0."""
    max_calls = draw(st.integers(min_value=1, max_value=1000))
    remaining = draw(st.integers(min_value=-10, max_value=0))
    max_tokens = draw(st.integers(min_value=2, max_value=1_000_000))
    used = draw(st.integers(min_value=0, max_value=max_tokens - 1))
    max_wall = draw(st.integers(min_value=60, max_value=7200))
    started_at = datetime.now(UTC).isoformat()
    return BudgetState(
        max_llm_calls=max_calls,
        remaining_llm_calls=remaining,
        max_tokens=max_tokens,
        tokens_used=used,
        max_wall_clock_s=max_wall,
        started_at=started_at,
    )


@st.composite
def budget_state_exhausted_tokens(draw: st.DrawFn) -> BudgetState:
    """Generate a BudgetState where tokens_used >= max_tokens."""
    max_calls = draw(st.integers(min_value=1, max_value=1000))
    remaining = draw(st.integers(min_value=1, max_value=max_calls))
    max_tokens = draw(st.integers(min_value=1, max_value=1_000_000))
    used = draw(st.integers(min_value=max_tokens, max_value=max_tokens + 100))
    max_wall = draw(st.integers(min_value=60, max_value=7200))
    started_at = datetime.now(UTC).isoformat()
    return BudgetState(
        max_llm_calls=max_calls,
        remaining_llm_calls=remaining,
        max_tokens=max_tokens,
        tokens_used=used,
        max_wall_clock_s=max_wall,
        started_at=started_at,
    )


# ---------------------------------------------------------------------------
# Property 6: Budget Exhaustion Detection
# ---------------------------------------------------------------------------


class TestBudgetExhaustionDetection:
    """Property 6: Budget Exhaustion Detection

    For any BudgetState where remaining_llm_calls <= 0 OR tokens_used >= max_tokens,
    BudgetGuard.check() should raise BudgetExhaustedError.
    For any BudgetState where all limits have capacity, check() should return None.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(budget=budget_state_exhausted_calls())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_raises_when_calls_exhausted(self, budget: BudgetState):
        """check() raises BudgetExhaustedError when remaining_llm_calls <= 0."""
        with pytest.raises(BudgetExhaustedError):
            BudgetGuard.check(budget)

    @given(budget=budget_state_exhausted_tokens())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_raises_when_tokens_exhausted(self, budget: BudgetState):
        """check() raises BudgetExhaustedError when tokens_used >= max_tokens."""
        with pytest.raises(BudgetExhaustedError):
            BudgetGuard.check(budget)

    @given(budget=budget_state_with_capacity())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_returns_none_when_capacity_available(self, budget: BudgetState):
        """check() returns None when all limits have remaining capacity."""
        result = BudgetGuard.check(budget)
        assert result is None


# ---------------------------------------------------------------------------
# Property 7: Budget Check Purity
# ---------------------------------------------------------------------------


class TestBudgetCheckPurity:
    """Property 7: Budget Check Purity

    BudgetGuard.check() should not mutate the input BudgetState.
    Calling check() twice with the same budget should produce the same result.

    **Validates: Requirement 7.4**
    """

    @given(budget=budget_state_with_capacity())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_check_does_not_mutate_budget(self, budget: BudgetState):
        """check() must not mutate the input BudgetState."""
        snapshot = copy.deepcopy(budget)
        BudgetGuard.check(budget)
        assert budget == snapshot

    @given(budget=budget_state_with_capacity())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_check_idempotent_pass(self, budget: BudgetState):
        """Calling check() twice on a valid budget returns None both times."""
        r1 = BudgetGuard.check(budget)
        r2 = BudgetGuard.check(budget)
        assert r1 is None
        assert r2 is None

    @given(budget=budget_state_exhausted_calls())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_check_idempotent_fail(self, budget: BudgetState):
        """Calling check() twice on an exhausted budget raises both times."""
        with pytest.raises(BudgetExhaustedError):
            BudgetGuard.check(budget)
        with pytest.raises(BudgetExhaustedError):
            BudgetGuard.check(budget)

    @given(budget=budget_state())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_check_does_not_mutate_any_budget(self, budget: BudgetState):
        """check() must not mutate the input regardless of outcome."""
        snapshot = copy.deepcopy(budget)
        try:
            BudgetGuard.check(budget)
        except BudgetExhaustedError:
            pass
        assert budget == snapshot


# ---------------------------------------------------------------------------
# Property 8: Budget Decrement Correctness
# ---------------------------------------------------------------------------


class TestBudgetDecrementCorrectness:
    """Property 8: Budget Decrement Correctness

    After decrement(budget, llm_calls=n, tokens_used=t):
      - result["remaining_llm_calls"] == budget["remaining_llm_calls"] - n
      - result["tokens_used"] == budget["tokens_used"] + t
      - All other fields must be unchanged.

    **Validates: Requirements 7.5, 7.6**
    """

    @given(
        budget=budget_state(),
        n=st.integers(min_value=0, max_value=100),
        t=st.integers(min_value=0, max_value=50_000),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_remaining_calls_decremented(self, budget: BudgetState, n: int, t: int):
        """remaining_llm_calls is decreased by exactly n."""
        result = BudgetGuard.decrement(budget, llm_calls=n, tokens_used=t)
        assert result["remaining_llm_calls"] == budget["remaining_llm_calls"] - n

    @given(
        budget=budget_state(),
        n=st.integers(min_value=0, max_value=100),
        t=st.integers(min_value=0, max_value=50_000),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_tokens_used_incremented(self, budget: BudgetState, n: int, t: int):
        """tokens_used is increased by exactly t."""
        result = BudgetGuard.decrement(budget, llm_calls=n, tokens_used=t)
        assert result["tokens_used"] == budget["tokens_used"] + t

    @given(
        budget=budget_state(),
        n=st.integers(min_value=0, max_value=100),
        t=st.integers(min_value=0, max_value=50_000),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_other_fields_unchanged(self, budget: BudgetState, n: int, t: int):
        """All fields except remaining_llm_calls and tokens_used are preserved."""
        result = BudgetGuard.decrement(budget, llm_calls=n, tokens_used=t)
        assert result["max_llm_calls"] == budget["max_llm_calls"]
        assert result["max_tokens"] == budget["max_tokens"]
        assert result["max_wall_clock_s"] == budget["max_wall_clock_s"]
        assert result["started_at"] == budget["started_at"]

    @given(
        budget=budget_state(),
        n=st.integers(min_value=0, max_value=100),
        t=st.integers(min_value=0, max_value=50_000),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_does_not_mutate_original(self, budget: BudgetState, n: int, t: int):
        """decrement() must not mutate the input BudgetState."""
        snapshot = copy.deepcopy(budget)
        BudgetGuard.decrement(budget, llm_calls=n, tokens_used=t)
        assert budget == snapshot


# ---------------------------------------------------------------------------
# Property 9: Budget Monotonicity
# ---------------------------------------------------------------------------


class TestBudgetMonotonicity:
    """Property 9: Budget Monotonicity

    After any sequence of decrement operations:
      - remaining_llm_calls only decreases or stays the same
      - tokens_used only increases or stays the same

    **Validates: Requirements 8.1, 8.2**
    """

    @given(
        budget=budget_state_with_capacity(),
        decrements=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=10),
                st.integers(min_value=0, max_value=5000),
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_remaining_calls_monotonically_decreasing(
        self, budget: BudgetState, decrements: list
    ):
        """remaining_llm_calls only decreases or stays the same across decrements."""
        current = budget
        prev_remaining = current["remaining_llm_calls"]
        for calls, tokens in decrements:
            current = BudgetGuard.decrement(
                current, llm_calls=calls, tokens_used=tokens
            )
            assert current["remaining_llm_calls"] <= prev_remaining, (
                f"remaining_llm_calls increased from {prev_remaining} "
                f"to {current['remaining_llm_calls']}"
            )
            prev_remaining = current["remaining_llm_calls"]

    @given(
        budget=budget_state_with_capacity(),
        decrements=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=10),
                st.integers(min_value=0, max_value=5000),
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_tokens_used_monotonically_increasing(
        self, budget: BudgetState, decrements: list
    ):
        """tokens_used only increases or stays the same across decrements."""
        current = budget
        prev_tokens = current["tokens_used"]
        for calls, tokens in decrements:
            current = BudgetGuard.decrement(
                current, llm_calls=calls, tokens_used=tokens
            )
            assert current["tokens_used"] >= prev_tokens, (
                f"tokens_used decreased from {prev_tokens} to {current['tokens_used']}"
            )
            prev_tokens = current["tokens_used"]
