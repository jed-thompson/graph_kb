"""Unit tests for backward compatibility when scope_contract and reading_order
are absent from decompose output.

Verifies that the topological sort and DecomposeNode task mapping work
correctly when the new fields are missing — no regression.

**Validates: Requirements 1.4, 10.4**
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Import the standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies (sentence_transformers).
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from topological_sort import topological_sort_sections  # noqa: E402

sys.path.pop(0)


class TestTopologicalSortBackwardCompat:
    """Verify topological sort works when scope_contract and reading_order
    are absent from task DAG tasks."""

    def test_no_reading_order_uses_topological_sort(self):
        """Tasks without reading_order fall back to topological sort."""
        hydrated = {"arch": "content", "api": "content", "tests": "content"}
        task_dag: dict[str, Any] = {
            "tasks": [
                {"id": "t1", "spec_section": "arch"},
                {"id": "t2", "spec_section": "api"},
                {"id": "t3", "spec_section": "tests"},
            ],
            "dag_edges": [["t1", "t2"], ["t2", "t3"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["arch", "api", "tests"]

    def test_no_scope_contract_no_reading_order(self):
        """Tasks with neither scope_contract nor reading_order work as before."""
        hydrated = {"section_a": "a", "section_b": "b"}
        task_dag: dict[str, Any] = {
            "tasks": [
                {"id": "t1", "spec_section": "section_a"},
                {"id": "t2", "spec_section": "section_b"},
            ],
            "dag_edges": [["t1", "t2"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["section_a", "section_b"]

    def test_partial_reading_order_falls_back(self):
        """When only some tasks have reading_order, topological sort is used."""
        hydrated = {"arch": "content", "api": "content", "tests": "content"}
        task_dag: dict[str, Any] = {
            "tasks": [
                {"id": "t1", "spec_section": "arch", "reading_order": 1},
                {"id": "t2", "spec_section": "api"},  # missing reading_order
                {"id": "t3", "spec_section": "tests", "reading_order": 3},
            ],
            "dag_edges": [["t1", "t2"], ["t2", "t3"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        # Should use topological sort, not reading_order
        assert result == ["arch", "api", "tests"]

    def test_all_reading_order_overrides_topological(self):
        """When all tasks have reading_order, it overrides topological sort."""
        hydrated = {"arch": "content", "api": "content", "tests": "content"}
        task_dag: dict[str, Any] = {
            "tasks": [
                {"id": "t1", "spec_section": "arch", "reading_order": 3},
                {"id": "t2", "spec_section": "api", "reading_order": 1},
                {"id": "t3", "spec_section": "tests", "reading_order": 2},
            ],
            "dag_edges": [["t1", "t2"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        # reading_order: api=1, tests=2, arch=3
        assert result == ["api", "tests", "arch"]

    def test_empty_dag_no_reading_order(self):
        """Empty DAG with no reading_order returns empty list."""
        result = topological_sort_sections({}, {"tasks": [], "dag_edges": []})
        assert result == []

    def test_single_task_no_reading_order(self):
        """Single task without reading_order works correctly."""
        hydrated = {"only_section": "content"}
        task_dag: dict[str, Any] = {
            "tasks": [{"id": "t1", "spec_section": "only_section"}],
            "dag_edges": [],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["only_section"]

    def test_disconnected_nodes_no_reading_order(self):
        """Disconnected nodes without reading_order preserve dict order."""
        hydrated = {"a": "content", "b": "content", "c": "content"}
        task_dag: dict[str, Any] = {
            "tasks": [
                {"id": "t1", "spec_section": "a"},
                {"id": "t2", "spec_section": "b"},
                {"id": "t3", "spec_section": "c"},
            ],
            "dag_edges": [],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["a", "b", "c"]

    def test_scope_contract_present_but_no_reading_order(self):
        """Tasks with scope_contract but no reading_order use topological sort.
        scope_contract is irrelevant to sort logic — only reading_order matters."""
        hydrated = {"arch": "content", "api": "content"}
        task_dag: dict[str, Any] = {
            "tasks": [
                {
                    "id": "t1",
                    "spec_section": "arch",
                    "scope_contract": {
                        "scope_includes": ["architecture"],
                        "scope_excludes": [],
                        "cross_cutting_owner": None,
                    },
                },
                {
                    "id": "t2",
                    "spec_section": "api",
                    "scope_contract": {
                        "scope_includes": ["api design"],
                        "scope_excludes": ["architecture"],
                        "cross_cutting_owner": None,
                    },
                },
            ],
            "dag_edges": [["t1", "t2"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["arch", "api"]
