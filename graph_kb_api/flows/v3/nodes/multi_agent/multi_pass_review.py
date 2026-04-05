"""
Multi-pass review node for multi-agent workflow.

Orchestrates review through multiple stages: completion, quality, security.
"""

from typing import Any, Dict

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class MultiPassReviewNode(BaseWorkflowNodeV3):
    """
    Orchestrates multi-pass review process.

    Cycles through review stages: completion -> quality -> security.
    Failed reviews trigger reprompt, successful reviews move forward.
    """

    # Review stages in order
    REVIEW_STAGES = ["completion", "quality", "security"]

    def __init__(self):
        super().__init__("multi_pass_review")
        self._messenger = None

    async def _execute_async(
        self,
        state: Dict[str, Any],
        services: Dict[str, Any]
    ) -> NodeExecutionResult:
        """
        Execute multi-pass review orchestration.

        Args:
            state: Current workflow state
            services: Injected services

        Returns:
            NodeExecutionResult with next review stage or final
        """
        try:
            self._setup_execution_context(state, services)

            current_stage = state.get('review_stage', 'none')

            # Determine next stage
            if current_stage == 'none':
                next_stage = 'completion'
                logger.info("Starting review: completion stage")
            elif current_stage in self.REVIEW_STAGES[:-1]:
                idx = self.REVIEW_STAGES.index(current_stage)
                next_stage = self.REVIEW_STAGES[idx + 1]
                logger.info(f"Advancing review: {current_stage} -> {next_stage}")
            else:
                # All stages complete, move to final
                logger.info("Review complete, moving to formatting")
                return NodeExecutionResult.success(
                    output={'review_stage': 'final'},
                    next_node='format_response'
                )

            # Check if previous stage passed
            if current_stage != 'none':
                last_pass = self._get_last_review_pass(state, current_stage)

                if not last_pass.get('passed', False):
                    # Failed review, trigger reprompt
                    return NodeExecutionResult.success(
                        output={
                            'review_stage': current_stage,
                            'reprompt_triggered': True,
                            'reprompt_reason': last_pass.get('feedback', 'Stage failed')
                        }
                    )

            # Move to next stage
            logger.info(f"Review stage {current_stage} completed, advancing to {next_stage}")

            return NodeExecutionResult.success(
                output={'review_stage': next_stage}
            )

        except Exception as e:
            logger.error(
                f"Multi-pass review failed: {e}",
                data={'node_type': self.node_name, 'error_type': type(e).__name__}
            )
            return NodeExecutionResult.error(
                f"Multi-pass review failed: {str(e)}",
                metadata={'node_type': self.node_name, 'error_type': type(e).__name__}
            )

    def _get_last_review_pass(self, state: Dict[str, Any], stage: str) -> Dict[str, Any]:
        """
        Get the most recent review pass for a stage.

        Args:
            state: Current workflow state
            stage: Current review stage

        Returns:
            Dict with passed status and feedback
        """
        review_passes = state.get('review_passes', [])

        # Filter passes for the stage before current
        # (or any pass if at 'none')
        if stage != 'none':
            stage_index = self.REVIEW_STAGES.index(stage) - 1
            if stage_index >= 0:
                stage_passes_for_stage = [
                    p for p in review_passes
                    if p.get('stage') == self.REVIEW_STAGES[stage_index]
                ]
            else:
                # At 'none', look for any pass
                stage_passes_for_stage = review_passes[-1:] if review_passes else []

        if not stage_passes_for_stage:
            # No previous pass found
            return {'passed': True, 'feedback': 'No previous review found'}

        # Get most recent pass
        last_pass = stage_passes_for_stage[-1] if stage_passes_for_stage else {}

        return {
            'passed': last_pass.get('passed', True),
            'feedback': last_pass.get('feedback', 'Review complete')
        }
