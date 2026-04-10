"""Property-based tests for topological_sort_sections().

Property 1: Topological sort completeness — For any set of hydrated sections
            and any valid task DAG, the output contains every key from the
            hydrated sections exactly once (no duplicates, no omissions).

Property 2: Dependency ordering — For any task DAG edge (A, B) where both A
            and B are in the hydrated sections, A appears before B in the
            topological sort result.

**Validates: Requirements 5.1, 5.2, 5.6, 11.1**
"""

from __future__ import annotations

import sys
import os
from typing import Any

from hypothesis import given, settings, HealthCheck, strategies as st

# Import the standalone utility module directly, bypassing the package
# __init__.py which triggers heavy dependencies (sentence_transformers).
_utils_dir = os.path.join(
    os.path.dirname(__file__), os.pardir,
    "graph_kb_api", "flows", "v3", "utils",
)
sys.path.insert(0, os.path.normpath(_utils_dir))
from topological_sort import topological_sort_sections  # noqa: E402

sys.path.pop(0)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def dag_and_sections_st(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, Any]]:
    """Generate a random valid DAG with matching hydrated_sections.

    Builds nodes with topological ordering guarantee (edges only point
    from lower-index to higher-index nodes) to ensure acyclicity.
    """
    num_nodes = draw(st.integers(min_value=0, max_value=15))
    section_keys = [f"section_{i}" for i in range(num_nodes)]

    # Build hydrated_sections with dummy content
    hydrated_sections: dict[str, str] = {}
    for key in section_keys:
        hydrated_sections[key] = f"Content for {key}"

    # Build tasks — each task maps to a section via spec_section
    tasks: list[dict[str, str]] = []
    for i, key in enumerate(section_keys):
        tasks.append({"id": f"task_{i}", "spec_section": key})

    # Build DAG edges — only from lower-index to higher-index (acyclic)
    dag_edges: list[list[str]] = []
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            if draw(st.booleans()):
                dag_edges.append([f"task_{i}", f"task_{j}"])

    task_dag: dict[str, Any] = {"tasks": tasks, "dag_edges": dag_edges}
    return hydrated_sections, task_dag


# ---------------------------------------------------------------------------
# Property 1: Topological sort completeness
# ---------------------------------------------------------------------------


class TestTopologicalSortCompleteness:
    """Property 1: Topological sort completeness.

    **Validates: Requirements 5.6, 11.1**
    """

    @given(data=dag_and_sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_output_contains_all_keys_exactly_once(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """For any valid DAG and sections, the output contains every key
        from hydrated_sections exactly once — no duplicates, no omissions.

        **Validates: Requirements 5.6, 11.1**
        """
        hydrated_sections, task_dag = data
        result = topological_sort_sections(hydrated_sections, task_dag)

        assert set(result) == set(hydrated_sections.keys()), (
            f"Output keys {set(result)} != input keys {set(hydrated_sections.keys())}"
        )
        assert len(result) == len(set(result)), (
            f"Duplicates found in result: {result}"
        )
        assert len(result) == len(hydrated_sections), (
            f"Result length {len(result)} != input length {len(hydrated_sections)}"
        )


# ---------------------------------------------------------------------------
# Property 2: Dependency ordering
# ---------------------------------------------------------------------------


class TestTopologicalSortDependencyOrdering:
    """Property 2: Dependency ordering.

    **Validates: Requirements 5.1, 5.2**
    """

    @given(data=dag_and_sections_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_dependencies_appear_before_dependents(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """For any edge (A, B) in the DAG where both A and B are in the
        hydrated sections, A appears before B in the result.

        **Validates: Requirements 5.1, 5.2**
        """
        hydrated_sections, task_dag = data
        result = topological_sort_sections(hydrated_sections, task_dag)

        tasks = task_dag.get("tasks", [])
        dag_edges = task_dag.get("dag_edges", [])

        task_id_to_key: dict[str, str] = {}
        for t in tasks:
            tid = t.get("id", "")
            key = t.get("spec_section", tid) or tid
            if key in hydrated_sections:
                task_id_to_key[tid] = key

        result_index = {k: i for i, k in enumerate(result)}
        for edge in dag_edges:
            src_key = task_id_to_key.get(edge[0])
            tgt_key = task_id_to_key.get(edge[1])
            if src_key and tgt_key and src_key in result_index and tgt_key in result_index:
                assert result_index[src_key] < result_index[tgt_key], (
                    f"Edge ({src_key} -> {tgt_key}): {src_key} at index "
                    f"{result_index[src_key]} should be before {tgt_key} at "
                    f"index {result_index[tgt_key]}. Full result: {result}"
                )


# ---------------------------------------------------------------------------
# Strategies for reading order
# ---------------------------------------------------------------------------


@st.composite
def dag_with_reading_order_st(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, Any]]:
    """Generate a random valid DAG where ALL tasks have reading_order.

    reading_order values are a permutation of 1..N so every task has a
    unique position.
    """
    num_nodes = draw(st.integers(min_value=1, max_value=15))
    section_keys = [f"section_{i}" for i in range(num_nodes)]

    hydrated_sections: dict[str, str] = {}
    for key in section_keys:
        hydrated_sections[key] = f"Content for {key}"

    # Assign unique reading_order via a permutation of 1..N
    reading_orders = draw(st.permutations(list(range(1, num_nodes + 1))))

    tasks: list[dict[str, Any]] = []
    for i, key in enumerate(section_keys):
        tasks.append({
            "id": f"task_{i}",
            "spec_section": key,
            "reading_order": reading_orders[i],
        })

    # Build DAG edges — only from lower-index to higher-index (acyclic)
    dag_edges: list[list[str]] = []
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            if draw(st.booleans()):
                dag_edges.append([f"task_{i}", f"task_{j}"])

    task_dag: dict[str, Any] = {"tasks": tasks, "dag_edges": dag_edges}
    return hydrated_sections, task_dag


@st.composite
def dag_without_reading_order_st(draw: st.DrawFn) -> tuple[dict[str, str], dict[str, Any]]:
    """Generate a random valid DAG where at least one task lacks reading_order.

    Some tasks may have reading_order, but at least one will not.
    """
    num_nodes = draw(st.integers(min_value=1, max_value=15))
    section_keys = [f"section_{i}" for i in range(num_nodes)]

    hydrated_sections: dict[str, str] = {}
    for key in section_keys:
        hydrated_sections[key] = f"Content for {key}"

    # Decide which tasks get reading_order — ensure at least one does NOT
    missing_idx = draw(st.integers(min_value=0, max_value=num_nodes - 1))

    tasks: list[dict[str, Any]] = []
    order_counter = 1
    for i, key in enumerate(section_keys):
        task: dict[str, Any] = {"id": f"task_{i}", "spec_section": key}
        if i != missing_idx:
            task["reading_order"] = order_counter
            order_counter += 1
        tasks.append(task)

    # Build DAG edges — only from lower-index to higher-index (acyclic)
    dag_edges: list[list[str]] = []
    for i in range(num_nodes):
        for j in range(i + 1, num_nodes):
            if draw(st.booleans()):
                dag_edges.append([f"task_{i}", f"task_{j}"])

    task_dag: dict[str, Any] = {"tasks": tasks, "dag_edges": dag_edges}
    return hydrated_sections, task_dag


# ---------------------------------------------------------------------------
# Property 7: Reading order override
# ---------------------------------------------------------------------------


class TestReadingOrderOverride:
    """Property 7: Reading order override.

    For any set of tasks where all tasks have reading_order, assembly sort
    orders by reading_order; when reading_order is absent, topological sort
    is used as fallback.

    **Validates: Requirements 10.3, 10.4**
    """

    @given(data=dag_with_reading_order_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_all_reading_order_sorts_by_reading_order(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """When all tasks have reading_order, sections are sorted by that
        value (ascending).

        **Validates: Requirements 10.3**
        """
        hydrated_sections, task_dag = data
        result = topological_sort_sections(hydrated_sections, task_dag)

        # Build expected order from reading_order values
        tasks = task_dag["tasks"]
        key_to_order: dict[str, int] = {}
        for t in tasks:
            key = t.get("spec_section", t["id"])
            key_to_order[key] = t["reading_order"]

        expected = sorted(hydrated_sections.keys(), key=lambda k: key_to_order[k])
        assert result == expected, (
            f"Expected reading_order sort {expected}, got {result}. "
            f"Orders: {key_to_order}"
        )

    @given(data=dag_without_reading_order_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_missing_reading_order_falls_back_to_topological(
        self, data: tuple[dict[str, str], dict[str, Any]]
    ):
        """When reading_order is absent from any task, topological sort is
        used as fallback — result still satisfies completeness and
        dependency ordering.

        **Validates: Requirements 10.4**
        """
        hydrated_sections, task_dag = data
        result = topological_sort_sections(hydrated_sections, task_dag)

        # Completeness: all keys present exactly once
        assert set(result) == set(hydrated_sections.keys())
        assert len(result) == len(hydrated_sections)

        # Dependency ordering: for every edge, source before target
        tasks = task_dag.get("tasks", [])
        dag_edges = task_dag.get("dag_edges", [])
        task_id_to_key: dict[str, str] = {}
        for t in tasks:
            tid = t.get("id", "")
            key = t.get("spec_section", tid) or tid
            if key in hydrated_sections:
                task_id_to_key[tid] = key

        result_index = {k: i for i, k in enumerate(result)}
        for edge in dag_edges:
            src_key = task_id_to_key.get(edge[0])
            tgt_key = task_id_to_key.get(edge[1])
            if src_key and tgt_key and src_key in result_index and tgt_key in result_index:
                assert result_index[src_key] < result_index[tgt_key], (
                    f"Edge ({src_key} -> {tgt_key}): dependency ordering violated"
                )
