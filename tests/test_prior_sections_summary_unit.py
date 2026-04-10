"""Unit tests for build_prior_sections_summary().

Tests: 0 completed tasks (empty string), 1 task, N tasks,
tasks with/without open questions, token budget truncation.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
"""

from __future__ import annotations

import os
import sys

# Import standalone utility modules directly, bypassing the package
# __init__.py which triggers heavy dependencies.
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

_estimator = TokenEstimator()


class TestPriorSectionsSummaryUnit:
    """Unit tests for build_prior_sections_summary.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
    """

    def test_zero_completed_tasks_returns_empty(self):
        """No completed tasks should return empty string.

        **Validates: Requirement 2.6**
        """
        results = [
            {"id": "t1", "name": "Sec A", "status": "pending", "output": "some content"},
            {"id": "t2", "name": "Sec B", "status": "failed", "output": "error"},
        ]
        assert build_prior_sections_summary(results, _estimator=_estimator) == ""

    def test_done_but_empty_output_returns_empty(self):
        """Done tasks with empty output should return empty string.

        **Validates: Requirements 2.2, 2.6**
        """
        results = [
            {"id": "t1", "name": "Sec A", "status": "done", "output": ""},
        ]
        assert build_prior_sections_summary(results, _estimator=_estimator) == ""

    def test_single_completed_task(self):
        """One completed task should produce header + one bullet.

        **Validates: Requirements 2.1, 2.2, 2.3**
        """
        results = [
            {
                "id": "task_001",
                "name": "Architecture Overview",
                "status": "done",
                "output": "This section defines the pipeline topology. It covers component boundaries. Data flow is described.",
            },
        ]
        summary = build_prior_sections_summary(results, _estimator=_estimator)
        assert summary.startswith("## Already Covered by Prior Sections\n")
        assert '"Architecture Overview" (task_001)' in summary
        assert summary.count("- Section") == 1

    def test_multiple_completed_tasks(self):
        """N completed tasks should produce N bullets.

        **Validates: Requirements 2.1, 2.2, 2.3**
        """
        results = [
            {"id": "t1", "name": "Sec A", "status": "done", "output": "Content A. Second sentence. Third."},
            {"id": "t2", "name": "Sec B", "status": "pending", "output": "Not done yet"},
            {"id": "t3", "name": "Sec C", "status": "done", "output": "Content C. More details."},
        ]
        summary = build_prior_sections_summary(results, _estimator=_estimator)
        assert summary.count("- Section") == 2
        assert '"Sec A" (t1)' in summary
        assert '"Sec C" (t3)' in summary
        assert '"Sec B"' not in summary

    def test_task_with_open_questions(self):
        """Tasks with open questions markers should include them.

        **Validates: Requirement 2.3**
        """
        output = (
            "This section covers authentication.\n\n"
            "### Open Questions\n"
            "- How should token refresh work?\n"
            "- What is the credential storage policy?\n"
            "- Should we support SSO?\n"
        )
        results = [
            {"id": "t1", "name": "Auth Flow", "status": "done", "output": output},
        ]
        summary = build_prior_sections_summary(results, _estimator=_estimator)
        assert "Open questions:" in summary
        assert "How should token refresh work?" in summary

    def test_task_with_assumptions_and_open_questions_header(self):
        """The '### Assumptions and Open Questions' header should also be detected.

        **Validates: Requirement 2.3**
        """
        output = (
            "Address normalization rules.\n\n"
            "### Assumptions and Open Questions\n"
            "- US-only addresses assumed\n"
        )
        results = [
            {"id": "t1", "name": "Address", "status": "done", "output": output},
        ]
        summary = build_prior_sections_summary(results, _estimator=_estimator)
        assert "Open questions:" in summary
        assert "US-only addresses assumed" in summary

    def test_task_without_open_questions(self):
        """Tasks without open questions should not include the marker.

        **Validates: Requirement 2.3**
        """
        results = [
            {"id": "t1", "name": "Simple", "status": "done", "output": "Just content. No questions."},
        ]
        summary = build_prior_sections_summary(results, _estimator=_estimator)
        assert "Open questions:" not in summary

    def test_token_budget_truncation(self):
        """When budget is tight, later tasks should be truncated.

        **Validates: Requirements 2.4, 2.5**
        """
        # Create many tasks with substantial output
        results = []
        for i in range(20):
            results.append(
                {
                    "id": f"t{i}",
                    "name": f"Section {i}",
                    "status": "done",
                    "output": f"This is section {i} with detailed content. " * 20,
                }
            )

        # Use a very small token budget
        summary = build_prior_sections_summary(results, max_tokens=100, _estimator=_estimator)

        if summary:
            actual_tokens = _estimator.count_tokens(summary)
            assert actual_tokens <= 100
            # Earlier sections should be preserved
            assert '"Section 0"' in summary

    def test_summary_truncates_long_output(self):
        """Individual task summaries should be capped at ~200 chars.

        **Validates: Requirement 2.3**
        """
        long_output = "A" * 500 + ". Second sentence. Third sentence."
        results = [
            {"id": "t1", "name": "Long", "status": "done", "output": long_output},
        ]
        summary = build_prior_sections_summary(results, _estimator=_estimator)
        # The summary for this task should be truncated with "..."
        assert "..." in summary

    def test_empty_task_results_list(self):
        """Empty list should return empty string.

        **Validates: Requirement 2.6**
        """
        assert build_prior_sections_summary([], _estimator=_estimator) == ""

    def test_preserves_earlier_sections_on_truncation(self):
        """Earlier (foundational) sections should be preserved when budget is exceeded.

        **Validates: Requirement 2.5**
        """
        results = [
            {"id": "t1", "name": "Foundation", "status": "done", "output": "Core architecture. Base patterns."},
            {"id": "t2", "name": "Details", "status": "done", "output": "Implementation details. " * 50},
            {"id": "t3", "name": "Late", "status": "done", "output": "Late section content. " * 50},
        ]
        # Budget enough for header + first task but not all three
        header_tokens = _estimator.count_tokens("## Already Covered by Prior Sections\n")
        first_line = '- Section "Foundation" (t1): Core architecture. Base patterns.\n'
        first_tokens = _estimator.count_tokens(first_line)
        tight_budget = header_tokens + first_tokens + 5  # Just barely enough for first

        summary = build_prior_sections_summary(results, max_tokens=tight_budget, _estimator=_estimator)
        assert '"Foundation"' in summary
        # Later sections may or may not fit depending on exact token counts
        actual_tokens = _estimator.count_tokens(summary)
        assert actual_tokens <= tight_budget
