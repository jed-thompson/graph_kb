"""
Approval node for the feature spec workflow.

Uses LangGraph ``interrupt`` to pause the workflow and present the final
validated spec to the user for review. The user can approve the spec
(routing to END) or reject it with change requests and specific
``sections_to_revise`` (routing back to the orchestrator for rework).
"""

from typing import Any, Dict, List

from langgraph.types import interrupt

from graph_kb_api.flows.v3.models import ServiceRegistry
from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3


class ApprovalNode(BaseWorkflowNodeV3):
    """User approval gate before workflow completion.

    When invoked, the node:
      1. Reads the ``final_output`` (assembled + validated spec) from state.
      2. Calls ``interrupt()`` with the spec content, pausing the workflow
         for user review.
      3. When the user resumes, processes their response to determine
         approval or rejection.
      4. On approval: sets ``user_approved=True`` so the workflow routes
         to END.
      5. On rejection: captures ``approval_feedback`` and
         ``sections_to_revise`` so the workflow routes back to the
         orchestrator for targeted rework.
    """

    def __init__(self) -> None:
        super().__init__("approval")

    async def _execute_async(self, state: Dict[str, Any], services: ServiceRegistry) -> NodeExecutionResult:
        """Present the final spec to the user and capture their decision.

        The ``interrupt()`` call suspends graph execution. When the user
        provides a response (via ``resume_workflow``), execution continues
        from here with the user's data.

        Expected user response format::

            {
                "approved": bool,
                "feedback": str,           # optional change requests
                "sections_to_revise": []   # optional list of section_ids
            }

        Returns NodeExecutionResult with output:
          - user_approved (bool)
          - approval_feedback (str) — empty string when approved
          - sections_to_revise (List[str]) — empty list when approved
        """
        self.logger.info("ApprovalNode: presenting spec for user approval")

        final_output: str = state.get("final_output", "")

        # Interrupt the workflow and wait for user review.
        interrupt_payload = {
            "type": "approval_needed",
            "final_output": final_output,
        }

        user_response = interrupt(interrupt_payload)

        self.logger.info("ApprovalNode: received user response, processing decision")

        # Parse the user response
        approved: bool = False
        feedback: str = ""
        sections_to_revise: List[str] = []

        if isinstance(user_response, dict):
            approved = bool(user_response.get("approved", False))
            feedback = str(user_response.get("feedback", ""))
            sections_to_revise = list(user_response.get("sections_to_revise", []))
        elif isinstance(user_response, bool):
            # Simple boolean approval shortcut
            approved = user_response
        elif isinstance(user_response, str):
            # String response treated as rejection with feedback
            approved = False
            feedback = user_response

        return NodeExecutionResult.success(
            output={
                "user_approved": approved,
                "approval_feedback": feedback,
                "sections_to_revise": sections_to_revise,
            }
        )
