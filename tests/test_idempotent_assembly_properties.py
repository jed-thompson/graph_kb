"""Property-based tests for idempotent assembly.

Property 6: Idempotent assembly — For any set of hydrated sections and task
            DAG, running topological sort and TOC generation twice on the same
            inputs shall produce identical output.

**Validates: Requirement 11.1**
"""

from __future__ import annotations

import re
import sys
import os
from typing import Any

from hypothesis import given, settings, HealthCheck, strategies as st

# ---------------------------------------------------------------------------
# Import standalone utilities directly to avoid heavy package init.
# ---------------------------------------------------------------------------
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from topological_sort import topological_sort_sections  # noqa: E402
from toc_generation import generate_toc as _generate_toc  # noqa: E402

sys.path.pop(0)


# ---------------------------------------------------------------------------
# Strategies — reuse the same DAG generation pattern from
# tests/test_topological_sort_properties.py
# ---------------------------------------------------------------------------


@st.composite
def dag_and_sections_st(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, Any]]:
    """Generate a random valid DAG with matching hydrated_sections.

    Builds nodes with topological ordering guarantee (edges only point
    from lower-index to higher-index nodes) to ensure acyclicity.
    """
    num_nodes = draw(st.integers(min_value=0, max_value=15))
    section_keys = [f"section_{i}" for i in range(num_nodes)]

    hydrated_sections: dict[str, str] = {}
    for key in section_keys:
        hydrated_sections[key] = f"Content for {key}"

    tasks: list[dict[str, str]] = []
    for i, key in enumerate(section_keys):
        tasks.append({"id": f"task_{i}", "spec_section": key})

    dag_edges: list[list[str]] = []
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            if draw(st.booleans()):
                dag_edges.append([f"task_{i}", f"task_{j}"])

    task_dag: dict[str, Any] = {"tasks": tasks, "dag_edges": dag_edges}
    return hydrated_sections, task_dag


# ---------------------------------------------------------------------------
# Property 6: Idempotent assembly
# ---------------------------------------------------------------------------


class TestIdempotentAssembly:
    """Property 6: Idempotent assembly.

    For any set of hydrated sections and task DAG, running topological sort
    and TOC generation twice on the same inputs produces identical output.

    **Validates: Requirement 11.1**
    """

    @given(data=dag_and_sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_topological_sort_is_idempotent(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """topological_sort_sections() returns the same result on two
        consecutive calls with the same inputs.

        **Validates: Requirement 11.1**
        """
        hydrated_sections, task_dag = data

        result_1 = topological_sort_sections(hydrated_sections, task_dag)
        result_2 = topological_sort_sections(hydrated_sections, task_dag)

        assert result_1 == result_2, (
            f"Topological sort not idempotent.\n"
            f"  First call:  {result_1}\n"
            f"  Second call: {result_2}"
        )

    @given(data=dag_and_sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_toc_generation_is_idempotent(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """_generate_toc() returns the same result on two consecutive calls
        with the same sorted keys.

        **Validates: Requirement 11.1**
        """
        hydrated_sections, task_dag = data

        sorted_keys = topological_sort_sections(hydrated_sections, task_dag)

        toc_1 = _generate_toc(sorted_keys)
        toc_2 = _generate_toc(sorted_keys)

        assert toc_1 == toc_2, (
            f"TOC generation not idempotent.\n"
            f"  First call:  {toc_1!r}\n"
            f"  Second call: {toc_2!r}"
        )

    @given(data=dag_and_sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_full_assembly_pipeline_is_idempotent(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """The combined topological sort + TOC generation pipeline produces
        identical output on two consecutive runs with the same inputs.

        **Validates: Requirement 11.1**
        """
        hydrated_sections, task_dag = data

        # Run 1
        sorted_keys_1 = topological_sort_sections(hydrated_sections, task_dag)
        toc_1 = _generate_toc(sorted_keys_1)

        # Run 2
        sorted_keys_2 = topological_sort_sections(hydrated_sections, task_dag)
        toc_2 = _generate_toc(sorted_keys_2)

        assert sorted_keys_1 == sorted_keys_2, (
            f"Sort not idempotent.\n"
            f"  Run 1: {sorted_keys_1}\n"
            f"  Run 2: {sorted_keys_2}"
        )
        assert toc_1 == toc_2, (
            f"TOC not idempotent.\n"
            f"  Run 1: {toc_1!r}\n"
            f"  Run 2: {toc_2!r}"
        )
