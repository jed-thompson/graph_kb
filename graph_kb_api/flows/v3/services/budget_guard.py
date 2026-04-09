"""BudgetGuard static utility class for enforcing global cost limits.

Provides check, decrement, is_exhausted, build_initial, increase, and
display operations against BudgetState.  All methods are @staticmethod
with no instance state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict

from graph_kb_api.flows.v3.state.plan_state import BudgetState


class BudgetExhaustedError(Exception):
    """Raised when any budget limit is exceeded."""

    pass


class BudgetGuard:
    """Enforces global cost limits across all LLM-calling nodes.

    Uses static methods only — no instance state.
    """

    # ── Fallback defaults (used when settings are unavailable) ───────
    _FALLBACK_MAX_LLM_CALLS: int = 500
    _FALLBACK_MAX_TOKENS: int = 500_000
    _FALLBACK_MAX_WALL_CLOCK_S: int = 1800
    _FALLBACK_INCREASE_FRACTION: float = 0.5
    _FALLBACK_INCREASE_MINIMUM: int = 10

    _NO_LIMIT = float("inf")

    # ── Settings accessors ─────────────────────────────────────────
    # Follows the same lazy-import pattern as TimeoutConfig.

    @staticmethod
    def get_default_max_llm_calls() -> int:
        try:
            from graph_kb_api.config import settings
            return settings.plan_max_llm_calls
        except Exception:
            return BudgetGuard._FALLBACK_MAX_LLM_CALLS

    @staticmethod
    def get_default_max_tokens() -> int:
        try:
            from graph_kb_api.config import settings
            return settings.plan_max_tokens
        except Exception:
            return BudgetGuard._FALLBACK_MAX_TOKENS

    @staticmethod
    def get_default_max_wall_clock_s() -> int:
        try:
            from graph_kb_api.config import settings
            return settings.plan_max_wall_clock_s
        except Exception:
            return BudgetGuard._FALLBACK_MAX_WALL_CLOCK_S

    @staticmethod
    def get_default_increase_fraction() -> float:
        try:
            from graph_kb_api.config import settings
            return settings.plan_budget_increase_fraction
        except Exception:
            return BudgetGuard._FALLBACK_INCREASE_FRACTION

    @staticmethod
    def get_default_increase_minimum() -> int:
        try:
            from graph_kb_api.config import settings
            return settings.plan_budget_increase_minimum
        except Exception:
            return BudgetGuard._FALLBACK_INCREASE_MINIMUM

    # ── Enforcement ────────────────────────────────────────────────

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

    # ── Factory ────────────────────────────────────────────────────

    @staticmethod
    def build_initial(seed: Dict[str, Any]) -> BudgetState:
        """Build a fresh ``BudgetState`` from *seed* values.

        Reads ``max_llm_calls``, ``max_tokens``, and ``max_wall_clock_s``
        from *seed*, falling back to class-level defaults.  Sets
        ``remaining_llm_calls`` equal to ``max_llm_calls``, ``tokens_used``
        to 0, and ``started_at`` to the current UTC timestamp.
        """
        max_calls = seed.get("max_llm_calls", BudgetGuard.get_default_max_llm_calls())
        return {
            "max_llm_calls": max_calls,
            "remaining_llm_calls": max_calls,
            "max_tokens": seed.get("max_tokens", BudgetGuard.get_default_max_tokens()),
            "tokens_used": 0,
            "max_wall_clock_s": seed.get("max_wall_clock_s", BudgetGuard.get_default_max_wall_clock_s()),
            "started_at": datetime.now(UTC).isoformat(),
        }

    # ── Budget increase ────────────────────────────────────────────

    @staticmethod
    def increase(
        budget: BudgetState,
        *,
        new_max_llm_calls: int | None = None,
        additional_llm_calls: int | None = None,
        max_tokens: int | None = None,
        max_wall_clock_s: int | None = None,
        reset_wall_clock: bool = True,
    ) -> BudgetState:
        """Return a new ``BudgetState`` with increased limits.

        Supports two modes for LLM call increases:

        *   **new_max_llm_calls**: Set a new maximum.  ``remaining_llm_calls``
            is set to ``max(current_remaining, 0) + max(new_max - old_max, 0)``
            so the user always gains at least the delta, even when remaining
            has drifted to 0 or negative.
        *   **additional_llm_calls**: Add an absolute increment.
            ``remaining_llm_calls`` becomes ``max(current_remaining, 0) + additional``.

        If neither is provided, a default 50 % increase is applied
        (minimum ``DEFAULT_INCREASE_MINIMUM``).

        ``max_tokens`` and ``max_wall_clock_s`` are simple overwrites when
        provided.  ``started_at`` is reset when *reset_wall_clock* is True
        so the full wall-clock window is available from this point forward.
        """
        old_max = budget.get("max_llm_calls", BudgetGuard.get_default_max_llm_calls())
        remaining = budget.get("remaining_llm_calls", 0)
        clamped_remaining = max(remaining, 0)

        if additional_llm_calls is not None:
            added = max(additional_llm_calls, 0)
            new_max = old_max + added
        elif new_max_llm_calls is not None:
            new_max = max(new_max_llm_calls, old_max)
            added = new_max - old_max
        else:
            fraction = BudgetGuard.get_default_increase_fraction()
            minimum = BudgetGuard.get_default_increase_minimum()
            added = max(int(old_max * fraction), minimum)
            new_max = old_max + added

        result: BudgetState = {
            **budget,
            "max_llm_calls": new_max,
            "remaining_llm_calls": clamped_remaining + added,
        }

        if max_tokens is not None:
            result["max_tokens"] = max_tokens
        if max_wall_clock_s is not None:
            result["max_wall_clock_s"] = max_wall_clock_s
        if reset_wall_clock:
            result["started_at"] = datetime.now(UTC).isoformat()

        return result

    # ── Display helper ─────────────────────────────────────────────

    @staticmethod
    def build_display(budget: BudgetState) -> Dict[str, Any]:
        """Build the frontend-facing budget display payload.

        Returns a dict with camelCase keys matching the frontend schema.
        """
        max_calls = budget.get("max_llm_calls", BudgetGuard.get_default_max_llm_calls())
        remaining = budget.get("remaining_llm_calls", 0)
        return {
            "maxLlmCalls": max_calls,
            "remainingLlmCalls": remaining,
            "tokensUsed": budget.get("tokens_used", 0),
            "maxTokens": budget.get("max_tokens", BudgetGuard.get_default_max_tokens()),
            "maxWallClockS": budget.get("max_wall_clock_s", BudgetGuard.get_default_max_wall_clock_s()),
            "startedAt": budget.get("started_at", ""),
            "usedLlmCalls": max(max_calls - remaining, 0),
        }
