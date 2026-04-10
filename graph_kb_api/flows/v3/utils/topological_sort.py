"""Topological sort utility for section ordering.

Provides Kahn's algorithm with stable tiebreaking by original dict order.
Extracted as a standalone module to avoid heavy import chains in tests.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


def topological_sort_sections(
    hydrated_sections: dict[str, str],
    task_dag: dict[str, Any],
) -> list[str]:
    """Sort section keys by dependency order using Kahn's algorithm.

    When ALL tasks in the task DAG carry a ``reading_order`` field, sections
    are sorted by that value instead (lower numbers first).  When
    ``reading_order`` is absent from *any* task, the function falls back to
    Kahn's algorithm with stable tiebreaking by original dict order.

    Sections with no dependencies (foundations) appear first.
    Sections not in the DAG at all are appended at the end.
    Original dict order is used as stable tiebreaker for sections
    at the same topological level.

    If a cycle is detected (len(result) < len(section_keys) after
    Kahn's completes), logs a warning and falls back to original
    dict iteration order.
    """
    tasks = task_dag.get("tasks", [])
    dag_edges = task_dag.get("dag_edges", [])
    section_keys = set(hydrated_sections.keys())
    original_order = list(hydrated_sections.keys())

    if not section_keys:
        return []

    # Map task IDs to section keys via spec_section field
    task_id_to_key: dict[str, str] = {}
    for t in tasks:
        tid = t.get("id", "")
        key = t.get("spec_section", tid) or tid
        if key in section_keys:
            task_id_to_key[tid] = key

    # ------------------------------------------------------------------
    # Reading-order override: when every task that maps to a hydrated
    # section carries a reading_order, sort by that value instead.
    # ------------------------------------------------------------------
    key_to_reading_order: dict[str, int] = {}
    for t in tasks:
        tid = t.get("id", "")
        key = task_id_to_key.get(tid)
        if key is not None and "reading_order" in t:
            key_to_reading_order[key] = t["reading_order"]

    if key_to_reading_order and set(key_to_reading_order.keys()) == section_keys:
        # All hydrated sections have a reading_order — use it
        sorted_keys = sorted(section_keys, key=lambda k: key_to_reading_order[k])
        return sorted_keys

    # ------------------------------------------------------------------
    # Fallback: topological sort via Kahn's algorithm
    # ------------------------------------------------------------------

    # Build adjacency list and in-degree map.
    # Use a set to deduplicate edges — duplicate edges would inflate
    # in-degree counts and break Kahn's algorithm.
    adjacency: dict[str, list[str]] = {k: [] for k in section_keys}
    in_degree: dict[str, int] = {k: 0 for k in section_keys}
    seen_edges: set[tuple[str, str]] = set()

    for edge in dag_edges:
        if not isinstance(edge, (list, tuple)) or len(edge) < 2:
            continue
        src, tgt = edge[0], edge[1]
        src_key = task_id_to_key.get(src)
        tgt_key = task_id_to_key.get(tgt)
        if src_key and tgt_key and src_key in section_keys and tgt_key in section_keys and src_key != tgt_key:
            edge_pair = (src_key, tgt_key)
            if edge_pair in seen_edges:
                continue
            seen_edges.add(edge_pair)
            adjacency[src_key].append(tgt_key)
            in_degree[tgt_key] += 1

    # Kahn's algorithm with stable tiebreaking by original dict order
    queue = deque(sorted(
        [k for k in section_keys if in_degree[k] == 0],
        key=lambda k: original_order.index(k),
    ))

    result: list[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        # Re-sort queue for stability
        queue = deque(sorted(queue, key=lambda k: original_order.index(k)))

    # Cycle detection fallback
    if len(result) < len(section_keys):
        logger.warning(
            "topological_sort_sections: cycle detected in task DAG — falling back to original dict order. "
            "Sorted %d of %d sections.",
            len(result),
            len(section_keys),
        )
        result = list(original_order)
    else:
        # Append any disconnected sections not reached by Kahn's
        for k in original_order:
            if k not in result:
                result.append(k)

    return result
