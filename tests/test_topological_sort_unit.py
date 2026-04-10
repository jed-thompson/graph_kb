"""Unit tests for topological_sort_sections().

Tests: linear chain, diamond DAG, disconnected nodes, single node,
empty DAG, and cyclic fallback.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**
"""

from __future__ import annotations

import sys
import os

# Import the standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies.
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from topological_sort import topological_sort_sections  # noqa: E402

sys.path.pop(0)


class TestTopologicalSortUnit:
    """Unit tests for topological_sort_sections.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**
    """

    def test_linear_chain(self):
        """A->B->C should produce [A, B, C].

        **Validates: Requirements 5.1, 5.2**
        """
        hydrated = {"A": "content A", "B": "content B", "C": "content C"}
        task_dag = {
            "tasks": [
                {"id": "t1", "spec_section": "A"},
                {"id": "t2", "spec_section": "B"},
                {"id": "t3", "spec_section": "C"},
            ],
            "dag_edges": [["t1", "t2"], ["t2", "t3"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["A", "B", "C"]

    def test_diamond_dag(self):
        """A->B, A->C, B->D, C->D should place A first and D last.

        **Validates: Requirements 5.1, 5.2**
        """
        hydrated = {
            "A": "content A", "B": "content B",
            "C": "content C", "D": "content D",
        }
        task_dag = {
            "tasks": [
                {"id": "t1", "spec_section": "A"},
                {"id": "t2", "spec_section": "B"},
                {"id": "t3", "spec_section": "C"},
                {"id": "t4", "spec_section": "D"},
            ],
            "dag_edges": [["t1", "t2"], ["t1", "t3"], ["t2", "t4"], ["t3", "t4"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result[0] == "A"
        assert result[-1] == "D"
        assert result.index("A") < result.index("B")
        assert result.index("A") < result.index("C")
        assert result.index("B") < result.index("D")
        assert result.index("C") < result.index("D")

    def test_disconnected_nodes(self):
        """Sections with no edges should appear in original dict order.

        **Validates: Requirements 5.3, 5.4**
        """
        hydrated = {"X": "x", "Y": "y", "Z": "z"}
        task_dag = {
            "tasks": [
                {"id": "t1", "spec_section": "X"},
                {"id": "t2", "spec_section": "Y"},
                {"id": "t3", "spec_section": "Z"},
            ],
            "dag_edges": [],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["X", "Y", "Z"]

    def test_single_node(self):
        """A single section should return that section.

        **Validates: Requirements 5.6**
        """
        hydrated = {"only": "content"}
        task_dag = {
            "tasks": [{"id": "t1", "spec_section": "only"}],
            "dag_edges": [],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["only"]

    def test_empty_dag(self):
        """Empty hydrated_sections should return empty list.

        **Validates: Requirements 5.6**
        """
        result = topological_sort_sections({}, {"tasks": [], "dag_edges": []})
        assert result == []

    def test_cyclic_fallback(self):
        """A cycle in the DAG should fall back to original dict order.

        **Validates: Requirements 5.5**
        """
        hydrated = {"A": "a", "B": "b", "C": "c"}
        task_dag = {
            "tasks": [
                {"id": "t1", "spec_section": "A"},
                {"id": "t2", "spec_section": "B"},
                {"id": "t3", "spec_section": "C"},
            ],
            "dag_edges": [["t1", "t2"], ["t2", "t3"], ["t3", "t1"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        # Cycle detected — falls back to original dict order
        assert result == ["A", "B", "C"]
        assert len(result) == 3

    def test_stable_tiebreaking(self):
        """Sections at the same topological level use original dict order.

        **Validates: Requirements 5.4**
        """
        # B and C both depend on A, no order between them
        hydrated = {"A": "a", "B": "b", "C": "c"}
        task_dag = {
            "tasks": [
                {"id": "t1", "spec_section": "A"},
                {"id": "t2", "spec_section": "B"},
                {"id": "t3", "spec_section": "C"},
            ],
            "dag_edges": [["t1", "t2"], ["t1", "t3"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result[0] == "A"
        # B comes before C in original dict order, so B should come first
        assert result.index("B") < result.index("C")

    def test_duplicate_edges_handled(self):
        """Duplicate edges in dag_edges should not break ordering.

        **Validates: Requirements 5.1, 5.2**
        """
        hydrated = {"A": "a", "B": "b", "C": "c"}
        task_dag = {
            "tasks": [
                {"id": "t1", "spec_section": "A"},
                {"id": "t2", "spec_section": "B"},
                {"id": "t3", "spec_section": "C"},
            ],
            # Duplicate edge t1->t2
            "dag_edges": [["t1", "t2"], ["t1", "t2"], ["t2", "t3"]],
        }
        result = topological_sort_sections(hydrated, task_dag)
        assert result == ["A", "B", "C"]
        assert len(result) == 3
