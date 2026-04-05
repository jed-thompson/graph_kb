"""
State pruner node for the feature spec workflow.

Runs after each orchestrator iteration to mitigate state bloat by:
  1. Removing resolved gaps from ``gaps_detected``.
  2. Pruning ``progress_events`` to keep only the last 10.
  3. Clearing stale agent execution fields (``agent_draft``,
     ``confidence_score``, ``confidence_rationale``, ``review_feedback``,
     ``review_verdict``).

Requirements traced: 12.1, 12.4, 12.5, 12.6
"""

from typing import Any, Dict

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)

# Maximum number of progress events to retain in state after pruning.
MAX_PROGRESS_EVENTS = 10


class StatePrunerNode:
    """Prunes state to prevent unbounded growth of accumulating fields.

    This node is wired to run after each orchestrator iteration so that
    resolved gaps are cleaned up, old progress events are discarded, and
    per-iteration agent execution fields are reset before the next cycle.
    """

    def __init__(self) -> None:
        self.node_name = "state_pruner"

    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("StatePrunerNode: pruning state")

        updates: Dict[str, Any] = {}

        # 1. Remove resolved gaps (keep only unresolved ones)
        gaps = state.get("gaps_detected", {}) or {}
        active_gaps = {
            gid: gap for gid, gap in gaps.items() if not gap.get("resolved", False)
        }
        updates["gaps_detected"] = active_gaps

        # 2. Prune progress_events to keep only the last MAX_PROGRESS_EVENTS
        events = state.get("progress_events", []) or []
        if len(events) > MAX_PROGRESS_EVENTS:
            updates["progress_events"] = events[-MAX_PROGRESS_EVENTS:]
        else:
            updates["progress_events"] = list(events)

        # 3. Clear stale agent execution fields
        updates["agent_draft"] = None
        updates["confidence_score"] = None
        updates["confidence_rationale"] = None
        updates["review_feedback"] = None
        updates["review_verdict"] = None

        removed_gaps = len(gaps) - len(active_gaps)
        pruned_events = max(0, len(events) - MAX_PROGRESS_EVENTS)
        logger.info(
            f"StatePrunerNode: removed {removed_gaps} resolved gaps, "
            f"pruned {pruned_events} old progress events, "
            f"cleared stale agent fields"
        )

        return updates
