"""
Section aggregator node for the feature spec workflow.

Collects approved sections into ``completed_sections``, advances
``current_task_index``, tracks the ``all_sections_complete`` flag, and
triggers periodic consistency checks every N completed sections
(configurable via ``consistency_check_interval``, default 3).

Requirements traced: 9.1, 21.1, 21.2
"""

from typing import Any, Dict

from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3


class SectionAggregatorNode(BaseWorkflowNodeV3):
    """Aggregates approved sections, tracks progress, triggers consistency checks.

    After the reviewer approves a section (or max reworks are exhausted),
    this node:
      1. Stores the approved draft in ``completed_sections[section_id]``.
      2. Increments ``current_task_index``.
      3. Sets ``all_sections_complete`` when every task has been processed.
      4. Sets ``trigger_consistency_check=True`` every
         ``consistency_check_interval`` completed sections.
    """

    def __init__(self) -> None:
        super().__init__("section_aggregator")

    async def _execute_async(
        self, state: Dict[str, Any], services: ServiceRegistry
    ) -> NodeExecutionResult:
        self.logger.info("SectionAggregatorNode: aggregating approved section")

        # --- Extract relevant state ---
        current_task: Dict[str, Any] = state.get("current_task", {}) or {}
        section_id: str = current_task.get("section_id", "unknown")
        agent_draft: str = state.get("agent_draft", "") or ""
        current_task_index: int = state.get("current_task_index", 0)
        total_tasks: int = state.get("total_tasks", 0)
        consistency_check_interval: int = state.get("consistency_check_interval", 3)
        existing_completed: Dict[str, str] = dict(
            state.get("completed_sections", {}) or {}
        )

        # --- Store the approved section ---
        new_completed = {section_id: agent_draft}

        # --- Advance task index ---
        new_task_index = current_task_index + 1

        # --- Determine if all sections are complete ---
        # Count total completed including this new one
        all_completed = {**existing_completed, **new_completed}
        all_sections_complete = new_task_index >= total_tasks

        # --- Determine if a consistency check should be triggered ---
        completed_count = len(all_completed)
        trigger_consistency_check = (
            consistency_check_interval > 0
            and completed_count > 0
            and completed_count % consistency_check_interval == 0
            and not all_sections_complete
        )

        # Also trigger consistency check when all sections are complete
        if all_sections_complete and completed_count > 0:
            trigger_consistency_check = True

        self.logger.info(
            f"SectionAggregatorNode: section '{section_id}' aggregated. "
            f"Progress: {new_task_index}/{total_tasks}. "
            f"Trigger consistency check: {trigger_consistency_check}"
        )

        return NodeExecutionResult.success(
            output={
                "completed_sections": new_completed,
                "current_task_index": new_task_index,
                "all_sections_complete": all_sections_complete,
                "trigger_consistency_check": trigger_consistency_check,
            }
        )
