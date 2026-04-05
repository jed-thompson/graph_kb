"""
Gap checker node for orchestrator subgraph.

Performs proactive gap detection on retrieved contexts to catch
missing information before agent dispatch.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Any, Dict, List

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import GapInfo
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3, ServiceRegistry


class GapCheckerNode(BaseWorkflowNodeV3):
    """
    Performs proactive gap detection on retrieved task contexts.

    Checks:
    - For unresolved existing gaps (blocks dispatch)
    - For new gaps in retrieved context (triggers clarification)

    If gaps found, routes to gap_detector instead of agent dispatch.
    """

    def __init__(self):
        super().__init__("gap_checker")

    @staticmethod
    def _generate_gap_id() -> str:
        """Return a unique gap identifier."""
        return f"gap_{uuid.uuid4().hex[:12]}"

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """Check for gaps in task contexts."""
        ready_tasks: List[Dict[str, Any]] = state.get("ready_tasks", [])
        task_contexts: Dict[str, Dict[str, Any]] = state.get("task_contexts", {})
        existing_gaps: Dict[str, Any] = state.get("gaps_detected", {}) or {}

        # Check for unresolved existing gaps first (Requirement 14.4)
        unresolved_gaps = {gid: g for gid, g in existing_gaps.items() if not g.get("resolved", False)}
        if unresolved_gaps:
            self.logger.info(f"GapChecker: {len(unresolved_gaps)} unresolved gaps — routing to gap_detector")
            return NodeExecutionResult.success(
                output={
                    "context_gaps": [],
                    "route_to": "gap_detector",
                    "awaiting_user_input": True,
                    "gaps_detected": existing_gaps,
                }
            )

        # Proactive gap detection on each task context
        all_gaps: List[GapInfo] = []

        for task in ready_tasks:
            task_id = task.get("task_id", "?")
            context = task_contexts.get(task_id, {})

            # Skip proactive gap detection when context is degraded
            if context.get("_degraded_context"):
                continue

            all_gaps.extend(self._detect_context_gaps(context, task))

        if all_gaps:
            self.logger.info(f"GapChecker: proactive detection found {len(all_gaps)} gap(s)")
            gaps_dict = {g.gap_id: asdict(g) for g in all_gaps}
            return NodeExecutionResult.success(
                output={
                    "context_gaps": [asdict(g) for g in all_gaps],
                    "gaps_detected": gaps_dict,
                    "route_to": "gap_detector",
                    "awaiting_user_input": True,
                }
            )

        self.logger.info("GapChecker: no gaps detected, proceeding to tool planning")
        return NodeExecutionResult.success(
            output={
                "context_gaps": [],
                "route_to": "tool_planner",
            }
        )

    def _detect_context_gaps(
        self,
        context_results: Dict[str, Any],
        task: Dict[str, Any],
    ) -> List[GapInfo]:
        """Proactively detect gaps during context retrieval.

        Checks for empty KB results, missing document references, and
        unresolved symbol references.
        """
        section_id: str = task.get("section_id", "unknown")
        gaps: List[GapInfo] = []

        for key, value in context_results.items():
            if key.startswith("symbol:"):
                symbol_name = key.split(":", 1)[1]
                if not value:
                    gaps.append(
                        GapInfo(
                            gap_id=self._generate_gap_id(),
                            section_id=section_id,
                            gap_type="empty_kb_result",
                            description=f"Graph KB query returned empty results for symbol '{symbol_name}'",
                            question=(
                                f"Could not find symbol '{symbol_name}' in the "
                                f"codebase. Can you provide details about this "
                                f"symbol or an alternative reference?"
                            ),
                            context=f"Task: {task.get('title', section_id)}",
                            source="proactive",
                        )
                    )

            elif key.startswith("doc:"):
                doc_name = key.split(":", 1)[1]
                if not value:
                    gaps.append(
                        GapInfo(
                            gap_id=self._generate_gap_id(),
                            section_id=section_id,
                            gap_type="missing_doc_ref",
                            description=f"Referenced document '{doc_name}' was not found in supplementary documents",
                            question=(
                                f"The document '{doc_name}' is referenced but "
                                f"not available. Can you provide this document "
                                f"or clarify the reference?"
                            ),
                            context=f"Task: {task.get('title', section_id)}",
                            source="proactive",
                        )
                    )

            elif key == "architecture_overview":
                if not value:
                    gaps.append(
                        GapInfo(
                            gap_id=self._generate_gap_id(),
                            section_id=section_id,
                            gap_type="empty_kb_result",
                            description="Architecture overview query returned empty results",
                            question=(
                                "Could not retrieve the architecture overview "
                                "from the codebase. Can you describe the high-level "
                                "architecture?"
                            ),
                            context=f"Task: {task.get('title', section_id)}",
                            source="proactive",
                        )
                    )

        return gaps
