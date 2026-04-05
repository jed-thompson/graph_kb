"""BudgetGuard static utility class for enforcing global cost limits.

Provides check, decrement, and is_exhausted operations against BudgetState.
All methods are @staticmethod with no instance state.
"""

from datetime import UTC, datetime

from graph_kb_api.flows.v3.state.plan_state import BudgetState


class BudgetExhaustedError(Exception):
    """Raised when any budget limit is exceeded."""

    pass


class BudgetGuard:
    """Enforces global cost limits across all LLM-calling nodes.

    Uses static methods only — no instance state.
    """

    _NO_LIMIT = float("inf")

    @staticmethod
    def check(budget: BudgetState) -> None:
        """Raise ``BudgetExhaustedError`` if any limit is exceeded.

        Checks remaining LLM calls, token usage, and wall-clock time.
        Returns ``None`` without mutation when all limits have capacity.
        Skips checks for fields that are absent from a partial BudgetState.
        """
        if budget.get("remaining_llm_calls", BudgetGuard._NO_LIMIT) <= 0:
            raise BudgetExhaustedError("LLM call limit reached")
        max_tokens = budget.get("max_tokens")
        tokens_used = budget.get("tokens_used", 0)
        if max_tokens is not None and tokens_used >= max_tokens:
            raise BudgetExhaustedError("Token limit reached")
        started_at = budget.get("started_at")
        max_wall = budget.get("max_wall_clock_s")
        if started_at and max_wall is not None:
            start = datetime.fromisoformat(started_at)
            elapsed = (datetime.now(UTC) - start).total_seconds()
            if elapsed >= max_wall:
                raise BudgetExhaustedError("Wall-clock limit reached")

    @staticmethod
    def decrement(
        budget: BudgetState, llm_calls: int = 0, tokens_used: int = 0
    ) -> BudgetState:
        """Return a new ``BudgetState`` with decremented counters.

        ``remaining_llm_calls`` is decreased by *llm_calls* and
        ``tokens_used`` is increased by *tokens_used*.  All other fields
        are preserved unchanged.
        """
        return {
            **budget,
            "remaining_llm_calls": budget.get("remaining_llm_calls", 0) - llm_calls,
            "tokens_used": budget.get("tokens_used", 0) + tokens_used,
        }

    @staticmethod
    def is_exhausted(budget: BudgetState) -> bool:
        """Return ``True`` if any budget limit is exceeded."""
        if budget.get("remaining_llm_calls", BudgetGuard._NO_LIMIT) <= 0:
            return True
        max_tokens = budget.get("max_tokens")
        tokens_used = budget.get("tokens_used", 0)
        if max_tokens is not None and tokens_used >= max_tokens:
            return True
        started_at = budget.get("started_at")
        max_wall = budget.get("max_wall_clock_s")
        if started_at and max_wall is not None:
            start = datetime.fromisoformat(started_at)
            elapsed = (datetime.now(UTC) - start).total_seconds()
            if elapsed >= max_wall:
                return True
        return False
