"""
Human input node for the feature spec workflow.

Uses LangGraph ``interrupt`` to pause the workflow when gaps are detected,
allowing the user to provide clarification. After the user responds, the
node stores responses in ``clarification_responses`` (merged by gap_id via
``operator.or_``), sets ``awaiting_user_input=False``, and routes back to
the orchestrator with enriched context.

DAG wiring: gap_detector → human_input → orchestrator
"""

from typing import Any, Dict, List

from langgraph.types import interrupt

from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3


class HumanInputNode(BaseWorkflowNodeV3):
    """Pauses the workflow for user clarification via LangGraph interrupt.

    When invoked, the node:
      1. Collects all unresolved gaps and their clarification questions
         from state.
      2. Calls ``interrupt()`` with the questions, pausing the workflow.
      3. When the user resumes with responses, stores them in
         ``clarification_responses`` keyed by gap_id.
      4. Marks the corresponding gaps as resolved.
      5. Sets ``awaiting_user_input=False`` so the orchestrator can proceed.
    """

    def __init__(self) -> None:
        super().__init__("human_input")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """Pause for user input and capture responses.

        The ``interrupt()`` call suspends the graph execution. When the
        user provides a response (via ``resume_workflow``), execution
        continues from here with the user's data.

        Returns NodeExecutionResult with output:
          - clarification_responses (Dict[str, str]) — gap_id -> user response
          - awaiting_user_input (bool) — set to False
          - gaps_detected (Dict[str, Dict]) — gaps marked as resolved
        """
        self.logger.info("HumanInputNode: pausing for user clarification")

        gaps: Dict[str, Dict[str, Any]] = dict(state.get("gaps_detected", {}) or {})
        questions: List[str] = list(state.get("clarification_questions", []) or [])

        # Build the interrupt payload — maps gap_id to its question
        unresolved_gaps: Dict[str, str] = {}
        for gap_id, gap_data in gaps.items():
            if not gap_data.get("resolved", False):
                unresolved_gaps[gap_id] = gap_data.get("question", "")

        # Interrupt the workflow and wait for user response.
        # The user's response should be a dict mapping gap_id -> answer string.
        interrupt_payload = {
            "type": "clarification_needed",
            "questions": questions,
            "gap_ids": list(unresolved_gaps.keys()),
            "gaps": unresolved_gaps,
        }

        user_response = interrupt(interrupt_payload)

        self.logger.info("HumanInputNode: received user response, resuming workflow")

        # user_response is expected to be Dict[str, str] mapping gap_id -> answer
        # but may also be a plain string (single-gap shortcut)
        responses: Dict[str, str] = {}
        if isinstance(user_response, dict):
            responses = {str(k): str(v) for k, v in user_response.items()}
        elif isinstance(user_response, str) and unresolved_gaps:
            # Single string response — assign to first unresolved gap
            first_gap_id = next(iter(unresolved_gaps))
            responses = {first_gap_id: user_response}

        # Mark responded gaps as resolved
        resolved_gaps: Dict[str, Dict[str, Any]] = {}
        for gap_id in responses:
            if gap_id in gaps:
                updated_gap = dict(gaps[gap_id])
                updated_gap["resolved"] = True
                updated_gap["resolution"] = responses[gap_id]
                resolved_gaps[gap_id] = updated_gap

        return NodeExecutionResult.success(
            output={
                "clarification_responses": responses,
                "awaiting_user_input": False,
                "gaps_detected": resolved_gaps,
            }
        )
