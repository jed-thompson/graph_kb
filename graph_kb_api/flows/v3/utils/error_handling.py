"""
Error handling utilities for the multi-agent feature spec workflow.

Provides:
  * ``retry_with_backoff`` — exponential backoff retry for LLM rate limits
  * ``handle_agent_exception`` — routes agent failures to reviewer with error info
  * ``fallback_to_supplementary_docs`` — Graph KB unavailable fallback

Requirements traced: 16.1, 16.2, 16.3, 16.4
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM rate-limit retry with exponential backoff  (Requirement 16.3)
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised when the LLM provider returns a rate-limit response."""


async def retry_with_backoff(
    fn: Callable[..., Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Any:
    """Execute *fn* with exponential backoff on ``RateLimitError``.

    Parameters
    ----------
    fn:
        An async callable (no arguments) to execute.
    max_retries:
        Maximum number of attempts (including the first).
    base_delay:
        Base delay in seconds; doubles on each retry.

    Returns
    -------
    The return value of *fn* on success.

    Raises
    ------
    RateLimitError
        If all retries are exhausted.
    Exception
        Any non-rate-limit exception is re-raised immediately.
    """
    for attempt in range(max_retries):
        try:
            return await fn()
        except RateLimitError:
            if attempt == max_retries - 1:
                logger.error(
                    "retry_with_backoff: all %d attempts exhausted", max_retries
                )
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                "retry_with_backoff: rate limited, retrying in %.1fs (attempt %d/%d)",
                delay,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Agent exception handling  (Requirement 16.1)
# ---------------------------------------------------------------------------


def handle_agent_exception(
    exception: Exception,
    task: Dict[str, Any],
    rework_count: int,
    max_reworks: int,
) -> Dict[str, Any]:
    """Return a state-update dict that routes an agent failure through review.

    If *rework_count* has reached *max_reworks*, the section is force-accepted
    with an error note so the workflow can continue.  Otherwise the task is
    sent back for rework with the error details as feedback.

    Parameters
    ----------
    exception:
        The exception raised by the agent.
    task:
        The ``SpecTask`` dict that was being executed.
    rework_count:
        Current rework attempt count for this task.
    max_reworks:
        Maximum allowed rework attempts.

    Returns
    -------
    Dict suitable for merging into ``FeatureSpecState``.
    """
    task_id = task.get("task_id", "unknown")
    section_id = task.get("section_id", "unknown")
    error_msg = f"{type(exception).__name__}: {exception}"

    logger.error(
        "handle_agent_exception: task=%s section=%s error=%s rework=%d/%d",
        task_id,
        section_id,
        error_msg,
        rework_count,
        max_reworks,
    )

    if rework_count >= max_reworks:
        # Force-accept with error note  (Requirement 5.3)
        return {
            "review_verdict": "approved",
            "review_feedback": (
                f"Agent failed after {max_reworks} retries: {error_msg}"
            ),
            "agent_draft": (
                f"[ERROR: Agent execution failed for section "
                f"'{section_id}' — {error_msg}]"
            ),
            "confidence_score": 0.0,
            "confidence_rationale": f"Agent execution failed: {error_msg}",
        }

    # Route back for rework  (Requirement 16.1)
    return {
        "review_verdict": "rework_needed",
        "review_feedback": f"Agent execution error: {error_msg}. Retrying.",
        "rework_count": rework_count + 1,
    }


# ---------------------------------------------------------------------------
# Graph KB unavailable fallback  (Requirement 16.2)
# ---------------------------------------------------------------------------


def fallback_to_supplementary_docs(
    task: Dict[str, Any],
    supplementary_docs: List[Dict[str, Any]],
    context_requirements: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build context from supplementary docs only when Graph KB is unavailable.

    Returns a context dict with:
      * Any ``doc:`` requirements resolved from *supplementary_docs*.
      * A ``_degraded_context`` flag set to ``True``.
      * A ``_degraded_context_warning`` message.

    Parameters
    ----------
    task:
        The ``SpecTask`` dict being processed.
    supplementary_docs:
        The list of supplementary document dicts from state.
    context_requirements:
        Explicit list of requirements; defaults to ``task["context_requirements"]``.

    Returns
    -------
    Dict with available context and degraded-context metadata.
    """
    reqs = context_requirements or task.get("context_requirements", [])
    context: Dict[str, Any] = {}

    for req in reqs:
        if req.startswith("doc:"):
            doc_name = req.split(":", 1)[1]
            for doc in supplementary_docs:
                if doc.get("name") == doc_name:
                    context[req] = doc.get("content", "")
                    break
            else:
                context[req] = None
        else:
            # KB-dependent requirements are unavailable
            context[req] = None

    context["_degraded_context"] = True
    context["_degraded_context_warning"] = (
        "Graph KB is unavailable. Context was built from supplementary "
        "documents only. Results may be less accurate."
    )

    logger.warning(
        "fallback_to_supplementary_docs: Graph KB unavailable for task '%s'; "
        "using supplementary docs only",
        task.get("task_id", "unknown"),
    )

    return context


# ---------------------------------------------------------------------------
# Parallel dispatch partial-failure handler  (Requirement 16.4)
# ---------------------------------------------------------------------------


def partition_dispatch_results(
    results: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Partition parallel dispatch results into successes and failures.

    Each result dict is expected to have an ``"error"`` key (truthy on
    failure) and a ``"task"`` key with the original task dict.

    Returns
    -------
    (successes, failures) — two lists of result dicts.
    """
    successes: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for result in results:
        if result.get("error"):
            failures.append(result)
        else:
            successes.append(result)
    return successes, failures
