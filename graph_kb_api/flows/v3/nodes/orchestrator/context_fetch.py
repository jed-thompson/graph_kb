"""
Context fetch node for orchestrator subgraph.

Retrieves context from Graph KB and supplementary documents for each ready task.
"""

from typing import Any, Dict, List

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.utils.error_handling import fallback_to_supplementary_docs


class ContextFetchNode(BaseWorkflowNodeV3):
    """
    Retrieves context for each ready task.

    For each ready task:
    - Fetch context based on context_requirements
    - Fall back to supplementary docs if Graph KB unavailable
    - Track degraded context state
    """

    def __init__(self):
        super().__init__("context_fetch")

    async def _execute_async(
        self, state: Dict[str, Any], services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """Retrieve context for all ready tasks."""
        ready_tasks: List[Dict[str, Any]] = state.get("ready_tasks", [])
        supplementary_docs: List[Dict[str, Any]] = state.get("supplementary_docs", [])
        task_contexts: Dict[str, Dict[str, Any]] = {}

        for task in ready_tasks:
            task_id = task.get("task_id", "?")
            try:
                context = await self._retrieve_context(task, supplementary_docs)
            except Exception as exc:
                self.logger.warning(
                    "ContextFetch: retrieval failed for task '%s': %s — "
                    "falling back to supplementary docs",
                    task_id,
                    exc,
                )
                context = fallback_to_supplementary_docs(task, supplementary_docs)

            task_contexts[task_id] = context

        self.logger.info(
            f"ContextFetch: retrieved context for {len(task_contexts)} task(s)"
        )
        return NodeExecutionResult.success(
            output={
                "task_contexts": task_contexts,
                "route_to": "gap_checker",
            }
        )

    async def _retrieve_context(
        self,
        task: Dict[str, Any],
        supplementary_docs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Retrieve context from Graph KB and supplementary documents for a task.

        If Graph KB is unavailable or KB-dependent requirements can't be fulfilled,
        falls back to supplementary-document-only context with a degraded-context warning (Requirement 16.2).
        """
        context: Dict[str, Any] = {}
        context_requirements: List[str] = task.get("context_requirements", [])
        kb_unavailable = False
        # Track KB-dependent requirements that couldn't be fulfilled
        unfulfilled_kb_requirements: List[str] = []

        for req in context_requirements:
            if req.startswith("symbol:"):
                try:
                    # Attempt Graph KB lookup — stubbed as None for now
                    # In production, this would query the Graph KB
                    result = None  # Placeholder for actual KB lookup
                    context[req] = result
                    if result is None:
                        # KB lookup returned None - requirement unfulfilled
                        unfulfilled_kb_requirements.append(req)
                except Exception:
                    kb_unavailable = True
                    context[req] = None
                    unfulfilled_kb_requirements.append(req)

            elif req.startswith("doc:"):
                doc_name = req.split(":", 1)[1]
                found = False
                for doc in supplementary_docs:
                    if doc.get("name") == doc_name:
                        context[req] = doc.get("content", "")
                        found = True
                        break
                if not found:
                    context[req] = None

            elif req == "architecture_overview":
                try:
                    result = None  # Placeholder for actual KB lookup
                    context[req] = result
                    if result is None:
                        unfulfilled_kb_requirements.append(req)
                except Exception:
                    kb_unavailable = True
                    context[req] = None
                    unfulfilled_kb_requirements.append(req)

            else:
                context[req] = None

        # If any KB-dependent requirements couldn't be fulfilled, mark as degraded
        # BUT only if supplementary docs CAN provide some fallback
        # If there are NO supplementary docs, this is a GAP (missing context),
        # not degraded context - gap_checker will detect and route to gap_detector
        if (kb_unavailable or unfulfilled_kb_requirements) and supplementary_docs:
            context = fallback_to_supplementary_docs(
                task, supplementary_docs, context_requirements
            )
            # Preserve the degraded context flag from fallback
            # (fallback_to_supplementary_docs returns _degraded_context: True)
        # else: no supplementary docs available, context remains as-is
        # (will be detected as a gap by gap_checker)

        return context
