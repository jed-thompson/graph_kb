"""Unit tests for BudgetGuard static utility class."""

from datetime import UTC, datetime, timedelta

import pytest

from graph_kb_api.flows.v3.services.budget_guard import (
    BudgetExhaustedError,
    BudgetGuard,
)
from graph_kb_api.flows.v3.state.plan_state import BudgetState


def _make_budget(**overrides) -> BudgetState:
    """Create a valid BudgetState with sensible defaults."""
    base: BudgetState = {
        "max_llm_calls": 200,
        "remaining_llm_calls": 100,
        "max_tokens": 500_000,
        "tokens_used": 0,
        "max_wall_clock_s": 1800,
        "started_at": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------


class TestCheck:
    def test_passes_when_budget_available(self):
        budget = _make_budget()
        assert BudgetGuard.check(budget) is None

    def test_raises_when_no_remaining_calls(self):
        budget = _make_budget(remaining_llm_calls=0)
        with pytest.raises(BudgetExhaustedError, match="LLM call limit"):
            BudgetGuard.check(budget)

    def test_raises_when_negative_remaining_calls(self):
        budget = _make_budget(remaining_llm_calls=-5)
        with pytest.raises(BudgetExhaustedError, match="LLM call limit"):
            BudgetGuard.check(budget)

    def test_raises_when_tokens_at_max(self):
        budget = _make_budget(tokens_used=500_000, max_tokens=500_000)
        with pytest.raises(BudgetExhaustedError, match="Token limit"):
            BudgetGuard.check(budget)

    def test_raises_when_tokens_exceed_max(self):
        budget = _make_budget(tokens_used=600_000, max_tokens=500_000)
        with pytest.raises(BudgetExhaustedError, match="Token limit"):
            BudgetGuard.check(budget)

    def test_raises_when_wall_clock_exceeded(self):
        past = (datetime.now(UTC) - timedelta(seconds=2000)).isoformat()
        budget = _make_budget(started_at=past, max_wall_clock_s=1800)
        with pytest.raises(BudgetExhaustedError, match="Wall-clock limit"):
            BudgetGuard.check(budget)

    def test_does_not_mutate_budget(self):
        budget = _make_budget()
        original = dict(budget)
        BudgetGuard.check(budget)
        assert budget == original


# ---------------------------------------------------------------------------
# decrement()
# ---------------------------------------------------------------------------


class TestDecrement:
    def test_decrements_llm_calls(self):
        budget = _make_budget(remaining_llm_calls=100)
        result = BudgetGuard.decrement(budget, llm_calls=3)
        assert result["remaining_llm_calls"] == 97

    def test_increments_tokens_used(self):
        budget = _make_budget(tokens_used=1000)
        result = BudgetGuard.decrement(budget, tokens_used=500)
        assert result["tokens_used"] == 1500

    def test_both_at_once(self):
        budget = _make_budget(remaining_llm_calls=50, tokens_used=1000)
        result = BudgetGuard.decrement(budget, llm_calls=2, tokens_used=300)
        assert result["remaining_llm_calls"] == 48
        assert result["tokens_used"] == 1300

    def test_preserves_other_fields(self):
        budget = _make_budget()
        result = BudgetGuard.decrement(budget, llm_calls=1, tokens_used=100)
        assert result["max_llm_calls"] == budget["max_llm_calls"]
        assert result["max_tokens"] == budget["max_tokens"]
        assert result["max_wall_clock_s"] == budget["max_wall_clock_s"]
        assert result["started_at"] == budget["started_at"]

    def test_returns_new_dict(self):
        budget = _make_budget()
        result = BudgetGuard.decrement(budget, llm_calls=1)
        assert result is not budget

    def test_does_not_mutate_original(self):
        budget = _make_budget(remaining_llm_calls=100, tokens_used=0)
        original = dict(budget)
        BudgetGuard.decrement(budget, llm_calls=5, tokens_used=200)
        assert budget == original

    def test_defaults_to_zero(self):
        budget = _make_budget(remaining_llm_calls=10, tokens_used=50)
        result = BudgetGuard.decrement(budget)
        assert result["remaining_llm_calls"] == 10
        assert result["tokens_used"] == 50


# ---------------------------------------------------------------------------
# is_exhausted()
# ---------------------------------------------------------------------------


class TestIsExhausted:
    def test_false_when_budget_available(self):
        budget = _make_budget()
        assert BudgetGuard.is_exhausted(budget) is False

    def test_true_when_no_remaining_calls(self):
        budget = _make_budget(remaining_llm_calls=0)
        assert BudgetGuard.is_exhausted(budget) is True

    def test_true_when_tokens_at_max(self):
        budget = _make_budget(tokens_used=500_000, max_tokens=500_000)
        assert BudgetGuard.is_exhausted(budget) is True

    def test_true_when_wall_clock_exceeded(self):
        past = (datetime.now(UTC) - timedelta(seconds=2000)).isoformat()
        budget = _make_budget(started_at=past, max_wall_clock_s=1800)
        assert BudgetGuard.is_exhausted(budget) is True

    def test_consistent_with_check(self):
        """is_exhausted should return True exactly when check raises."""
        budget = _make_budget(remaining_llm_calls=0)
        assert BudgetGuard.is_exhausted(budget) is True
        with pytest.raises(BudgetExhaustedError):
            BudgetGuard.check(budget)


# ---------------------------------------------------------------------------
# Static method verification
# ---------------------------------------------------------------------------


class TestStaticMethods:
    def test_check_is_static(self):
        assert isinstance(BudgetGuard.__dict__["check"], staticmethod)

    def test_decrement_is_static(self):
        assert isinstance(BudgetGuard.__dict__["decrement"], staticmethod)

    def test_is_exhausted_is_static(self):
        assert isinstance(BudgetGuard.__dict__["is_exhausted"], staticmethod)
