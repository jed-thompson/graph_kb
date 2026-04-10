"""Property-based tests for build_prior_sections_summary().

Property 3: Summary token bound — For any list of task results with random
            output lengths, the prior sections summary shall never exceed
            max_tokens tokens, and shall only contain entries from tasks
            with status "done" and non-empty output.

**Validates: Requirements 2.2, 2.4, 2.5**
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

from hypothesis import given, settings, HealthCheck, strategies as st

# Import standalone utility modules directly, bypassing the package
# __init__.py which triggers heavy dependencies (sentence_transformers).
_utils_dir = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "graph_kb_api",
    "flows",
    "v3",
    "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from prior_sections_summary import build_prior_sections_summary  # noqa: E402
from token_estimation import TokenEstimator  # noqa: E402

sys.path.pop(0)

# Shared estimator instance for all tests
_estimator = TokenEstimator()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_STATUS_VALUES = st.sampled_from(["done", "pending", "failed", "in_progress"])


@st.composite
def task_results_st(draw: st.DrawFn) -> list[dict[str, Any]]:
    """Generate a random list of task result dicts."""
    num_tasks = draw(st.integers(min_value=0, max_value=20))
    results: list[dict[str, Any]] = []
    for i in range(num_tasks):
        status = draw(_STATUS_VALUES)
        # Generate output text of varying lengths
        output = draw(
            st.one_of(
                st.just(""),
                st.text(
                    min_size=1,
                    max_size=2000,
                    alphabet=st.characters(
                        whitelist_categories=("L", "N", "P", "Z"),
                        whitelist_characters="\n.- ",
                    ),
                ),
            )
        )
        # Optionally include open questions markers
        if draw(st.booleans()) and output:
            marker = draw(
                st.sampled_from(
                    [
                        "### Open Questions",
                        "### Assumptions and Open Questions",
                        "## Open Questions",
                    ]
                )
            )
            oq_items = draw(
                st.lists(
                    st.text(
                        min_size=1,
                        max_size=50,
                        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
                    ),
                    min_size=0,
                    max_size=5,
                )
            )
            oq_block = f"\n{marker}\n" + "\n".join(f"- {item}" for item in oq_items)
            output = output + oq_block

        results.append(
            {
                "id": f"task_{i}",
                "name": f"Section {i}",
                "status": status,
                "output": output,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Property 3: Summary token bound
# ---------------------------------------------------------------------------


class TestSummaryTokenBound:
    """Property 3: Summary token bound.

    **Validates: Requirements 2.2, 2.4, 2.5**
    """

    @given(
        task_results=task_results_st(),
        max_tokens=st.integers(min_value=10, max_value=3000),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_never_exceeds_max_tokens(
        self,
        task_results: list[dict[str, Any]],
        max_tokens: int,
    ):
        """For any list of task results, the summary token count
        never exceeds max_tokens.

        **Validates: Requirements 2.4, 2.5**
        """
        result = build_prior_sections_summary(
            task_results, max_tokens=max_tokens, _estimator=_estimator
        )
        if not result:
            return  # Empty string is always within budget

        actual_tokens = _estimator.count_tokens(result)
        assert actual_tokens <= max_tokens, (
            f"Summary has {actual_tokens} tokens, exceeds max_tokens={max_tokens}. "
            f"Summary length: {len(result)} chars"
        )

    @given(task_results=task_results_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_summary_only_contains_done_nonempty_tasks(
        self,
        task_results: list[dict[str, Any]],
    ):
        """The summary shall only contain entries from tasks with
        status "done" and non-empty output.

        **Validates: Requirements 2.2**
        """
        result = build_prior_sections_summary(task_results, _estimator=_estimator)
        if not result:
            return

        # Extract all task IDs mentioned in the summary
        mentioned_ids = set(re.findall(r"\(task_\d+\)", result))

        # Build set of eligible task IDs
        eligible_ids = set()
        for tr in task_results:
            if tr.get("status") == "done" and tr.get("output"):
                eligible_ids.add(f"({tr['id']})")

        assert mentioned_ids.issubset(eligible_ids), (
            f"Summary mentions {mentioned_ids - eligible_ids} which are not "
            f"done+non-empty tasks. Eligible: {eligible_ids}"
        )
