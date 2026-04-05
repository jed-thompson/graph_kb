"""Property-based test for decompose DAG acyclicity.

Property 20: Decompose DAG Acyclicity — For any result from ``run_decompose``,
             ``dependency_graph`` is a valid DAG with no cycles.

**Validates: Requirements 13.3**

Since ``run_decompose`` is currently a stub (raises NotImplementedError),
these tests validate the *contract* that any dict returned by
``run_decompose`` must satisfy.  A helper ``check_dag_acyclicity``
encodes the invariant and is exercised with Hypothesis-generated data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st


# ---------------------------------------------------------------------------
# Contract helper
# ---------------------------------------------------------------------------


def check_dag_acyclicity(dependency_graph: Dict[str, List[str]]) -> None:
    """Assert that a dependency_graph is a valid DAG with no cycles.

    Uses iterative DFS with a recursion stack to detect cycles.

    Raises ``AssertionError`` if:
    - ``dependency_graph`` is not a dict
    - Any value in the dict is not a list of strings
    - The graph contains a cycle
    """
    assert isinstance(dependency_graph, dict), (
        f"dependency_graph must be a dict, got {type(dependency_graph).__name__}"
    )

    for node, deps in dependency_graph.items():
        assert isinstance(deps, list), (
            f"dependencies for '{node}' must be a list, got {type(deps).__name__}"
        )
        for dep in deps:
            assert isinstance(dep, str), (
                f"each dependency must be a string, got {type(dep).__name__}"
            )

    # Cycle detection via DFS with three-color marking:
    # WHITE = unvisited, GRAY = in current path, BLACK = fully processed
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {}

    # Include all nodes: both keys and referenced dependencies
    all_nodes: Set[str] = set(dependency_graph.keys())
    for deps in dependency_graph.values():
        all_nodes.update(deps)

    for node in all_nodes:
        color[node] = WHITE

    def _has_cycle_from(start: str) -> bool:
        """Iterative DFS from *start*; returns True if a cycle is found."""
        stack = [(start, False)]  # (node, is_backtrack)
        while stack:
            node, is_backtrack = stack.pop()
            if is_backtrack:
                color[node] = BLACK
                continue
            if color[node] == GRAY:
                return True
            if color[node] == BLACK:
                continue
            color[node] = GRAY
            stack.append((node, True))  # backtrack marker
            for dep in dependency_graph.get(node, []):
                if color[dep] == GRAY:
                    return True
                if color[dep] == WHITE:
                    stack.append((dep, False))
        return False

    for node in all_nodes:
        if color[node] == WHITE:
            assert not _has_cycle_from(node), (
                f"dependency_graph contains a cycle involving node '{node}'"
            )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


# Generate valid DAGs by creating nodes and only allowing edges to
# nodes with a *lower* index (topological ordering guarantees no cycles).
@st.composite
def valid_dag_st(draw: st.DrawFn) -> Dict[str, List[str]]:
    """Generate an arbitrary valid DAG as Dict[str, List[str]]."""
    num_nodes = draw(st.integers(min_value=0, max_value=15))
    node_names = [f"node_{i}" for i in range(num_nodes)]
    graph: Dict[str, List[str]] = {}
    for i, name in enumerate(node_names):
        # Only depend on nodes with a lower index → guarantees acyclicity
        possible_deps = node_names[:i]
        deps = draw(
            st.lists(
                st.sampled_from(possible_deps) if possible_deps else st.nothing(),
                max_size=min(len(possible_deps), 5),
                unique=True,
            )
        )
        graph[name] = deps
    return graph


@st.composite
def cyclic_graph_st(draw: st.DrawFn) -> Dict[str, List[str]]:
    """Generate a graph that is guaranteed to contain at least one cycle."""
    num_nodes = draw(st.integers(min_value=2, max_value=10))
    node_names = [f"node_{i}" for i in range(num_nodes)]

    # Start with a valid DAG structure
    graph: Dict[str, List[str]] = {name: [] for name in node_names}

    # Inject a cycle: pick two distinct nodes and create a directed cycle
    cycle_len = draw(st.integers(min_value=2, max_value=num_nodes))
    cycle_nodes = draw(st.permutations(node_names).map(lambda p: list(p[:cycle_len])))

    for i in range(len(cycle_nodes)):
        src = cycle_nodes[i]
        dst = cycle_nodes[(i + 1) % len(cycle_nodes)]
        if dst not in graph[src]:
            graph[src].append(dst)

    return graph


# ---------------------------------------------------------------------------
# Property 20: Decompose DAG Acyclicity
# ---------------------------------------------------------------------------


class TestDecomposeDAGAcyclicity:
    """Property 20: Decompose DAG Acyclicity — For any result from
    ``run_decompose``, ``dependency_graph`` is a valid DAG with no cycles.

    **Validates: Requirements 13.3**
    """

    @given(graph=valid_dag_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_dags_pass_check(self, graph: Dict[str, List[str]]):
        """Any topologically-ordered graph passes the acyclicity check.

        **Validates: Requirements 13.3**
        """
        check_dag_acyclicity(graph)

    @given(graph=cyclic_graph_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_cyclic_graphs_fail_check(self, graph: Dict[str, List[str]]):
        """Any graph with an injected cycle fails the acyclicity check.

        **Validates: Requirements 13.3**
        """
        with pytest.raises(AssertionError, match="contains a cycle"):
            check_dag_acyclicity(graph)

    def test_empty_graph_passes(self):
        """An empty dependency graph is a valid DAG.

        **Validates: Requirements 13.3**
        """
        check_dag_acyclicity({})

    def test_single_node_no_deps_passes(self):
        """A single node with no dependencies is a valid DAG.

        **Validates: Requirements 13.3**
        """
        check_dag_acyclicity({"story_1": []})

    def test_self_loop_fails(self):
        """A node depending on itself is a cycle.

        **Validates: Requirements 13.3**
        """
        with pytest.raises(AssertionError, match="contains a cycle"):
            check_dag_acyclicity({"story_1": ["story_1"]})

    def test_two_node_cycle_fails(self):
        """Two nodes forming a mutual dependency is a cycle.

        **Validates: Requirements 13.3**
        """
        with pytest.raises(AssertionError, match="contains a cycle"):
            check_dag_acyclicity(
                {
                    "story_1": ["story_2"],
                    "story_2": ["story_1"],
                }
            )

    def test_linear_chain_passes(self):
        """A linear chain (A→B→C) is a valid DAG.

        **Validates: Requirements 13.3**
        """
        check_dag_acyclicity(
            {
                "story_1": [],
                "story_2": ["story_1"],
                "story_3": ["story_2"],
            }
        )

    def test_diamond_dag_passes(self):
        """A diamond-shaped DAG (A→B, A→C, B→D, C→D) is valid.

        **Validates: Requirements 13.3**
        """
        check_dag_acyclicity(
            {
                "A": [],
                "B": ["A"],
                "C": ["A"],
                "D": ["B", "C"],
            }
        )

    def test_non_dict_graph_fails(self):
        """A non-dict dependency_graph fails the check.

        **Validates: Requirements 13.3**
        """
        with pytest.raises(AssertionError, match="must be a dict"):
            check_dag_acyclicity("not a dict")  # type: ignore[arg-type]

    def test_non_list_deps_fails(self):
        """Dependencies that are not a list fail the check.

        **Validates: Requirements 13.3**
        """
        with pytest.raises(AssertionError, match="must be a list"):
            check_dag_acyclicity({"story_1": "story_2"})  # type: ignore[dict-item]

    def test_non_string_dep_fails(self):
        """A non-string dependency entry fails the check.

        **Validates: Requirements 13.3**
        """
        with pytest.raises(AssertionError, match="must be a string"):
            check_dag_acyclicity({"story_1": [123]})  # type: ignore[list-item]

    @given(graph=valid_dag_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_dag_in_decompose_result(self, graph: Dict[str, List[str]]):
        """A full run_decompose result with a valid DAG passes the check.

        **Validates: Requirements 13.3**
        """
        result: Dict[str, Any] = {
            "stories": [],
            "tasks": [],
            "dependency_graph": graph,
            "total_story_points": 0,
        }
        check_dag_acyclicity(result["dependency_graph"])
