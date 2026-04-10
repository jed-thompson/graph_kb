"""BaseApprovalNode — shared approval workflow for phase gates.

Encapsulates the ~85% shared logic across ResearchApprovalNode,
PlanningApprovalNode, and AssemblyApprovalNode.  Subclasses override
only phase-specific hooks.

Requirements: 6.1, 6.2
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any, Generic, TypeVar

from langgraph.types import RunnableConfig, interrupt

from graph_kb_api.flows.v3.models.node_models import NodeExecutionResult
from graph_kb_api.flows.v3.models.types import ThreadConfigurable
from graph_kb_api.flows.v3.nodes.subgraph_aware_node import NodeContext, SubgraphAwareNode
from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
from graph_kb_api.flows.v3.state.plan_state import (
    ApprovalInterruptPayload,
    ArtifactRef,
    BasePlanSubgraphState,
    InterruptOption,
    PhaseFingerprint,
)
from graph_kb_api.websocket.plan_events import emit_phase_complete

logger = logging.getLogger(__name__)

S = TypeVar("S", bound=BasePlanSubgraphState)


class BaseApprovalNode(SubgraphAwareNode[S], Generic[S]):
    """Base class for phase approval gates.

    Encapsulates the shared approval workflow:
    1. Build phase-specific summary via ``_build_summary()``
    2. Load context items via ``build_context_items_summary()``
    3. Construct interrupt payload with ``_build_payload()``
    4. Issue ``interrupt()`` and wait for user response
    5. Process response via ``_process_decision()``
    6. Emit phase complete event on approval
    7. Store fingerprint on approval

    Subclasses override only:
    - ``_build_summary(state)`` → dict
    - ``_build_payload_extras(state, summary)`` → dict  (optional tasks, etc.)
    - ``_get_approval_options()`` → list[InterruptOption]
    - ``_get_approval_message(summary)`` → str
    - ``_process_approve(state, feedback)`` → dict
    - ``_process_revise(state, feedback)`` → dict  (optional)
    - ``_process_reject(state, feedback)`` → dict
    """

    # ── Phase data key ────────────────────────────────────────────
    # Subclasses set this to the state key that holds the phase-specific
    # data dict where approval_decision / approval_feedback are stored.
    # e.g. "research", "plan", "completeness"
    phase_data_key: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip validation for abstract intermediate classes
        if getattr(cls, "__abstractmethods__", None):
            return
        if not cls.phase_data_key:
            raise TypeError(
                f"{cls.__name__} must set 'phase_data_key' to the state key "
                f"holding phase-specific approval data (e.g. 'research', 'plan')"
            )

    # ── Abstract hooks (must override) ────────────────────────────

    @abstractmethod
    def _build_summary(self, state: S) -> dict[str, Any]:
        """Build the phase-specific summary dict for the interrupt payload."""
        ...

    @abstractmethod
    def _get_approval_options(self) -> list[InterruptOption]:
        """Return the list of approval options shown to the user."""
        ...

    @abstractmethod
    def _get_approval_message(self, summary: dict[str, Any]) -> str:
        """Return the human-readable approval message."""
        ...

    @abstractmethod
    def _process_approve(self, state: S, feedback: str) -> dict[str, Any]:
        """Return the output dict additions for an 'approve' decision.

        Should NOT include ``completed_phases`` or ``fingerprints`` — those
        are handled by the base class.
        """
        ...

    @abstractmethod
    def _process_reject(self, state: S, feedback: str) -> dict[str, Any]:
        """Return the output dict for a 'reject' decision.

        Should include ``workflow_status``, ``paused_phase``, ``error``, and
        the phase data with ``rejected=True``.
        """
        ...

    # ── Optional hooks (override when needed) ─────────────────────

    def _build_payload_extras(self, state: S, summary: dict[str, Any]) -> dict[str, Any]:
        """Override to add phase-specific payload fields (e.g. tasks list).

        Returned dict is merged into the interrupt payload.
        """
        return {}

    def _process_revise(self, state: S, feedback: str) -> dict[str, Any]:
        """Override to handle 'revise' / 'request_more' decisions.

        Default returns empty dict (no revision support).
        """
        return {}

    # ── Shared workflow ───────────────────────────────────────────

    async def _execute_step(self, state: S, config: RunnableConfig) -> NodeExecutionResult:
        """Shared approval workflow — delegates to hooks for phase-specific logic."""
        ctx = self._unpack(state, config)

        # 1. Build phase-specific summary
        summary = self._build_summary(state)

        # 2. Load context items
        context_items = await self._load_context_items(
            state.get("session_id"),
            state.get("research", {}),
            state.get("context"),
        )

        # 3. Construct interrupt payload
        payload: ApprovalInterruptPayload = {
            "type": "approval",
            "phase": self.phase,
            "step": "approval",
            "summary": summary,
            "message": self._get_approval_message(summary),
            "options": self._get_approval_options(),
            "artifacts": self._serialize_artifacts(state.get("artifacts", {})),
            "context_items": context_items,
        }

        # Merge any phase-specific extras (e.g. tasks list for planning)
        extras = self._build_payload_extras(state, summary)
        if extras:
            payload.update(extras)  # type: ignore[typeddict-item]

        # 4. Interrupt and wait for user response
        approval_response: dict[str, Any] = interrupt(payload)

        # 5. Route decision
        decision = approval_response.get("decision", "approve")
        feedback = approval_response.get("feedback", "")

        # 6. Delegate to the appropriate hook
        if decision == "approve":
            output = self._process_approve(state, feedback)
            # Store fingerprint for dirty-detection on backward navigation
            phase_data = output.get(self.phase_data_key, {})
            fp_hash: str = FingerprintTracker.compute_phase_data_fingerprint(
                self.phase, phase_data
            )
            existing_fps: dict[str, PhaseFingerprint] = state.get("fingerprints", {})
            output["fingerprints"] = FingerprintTracker.update_fingerprint(
                existing_fps,
                self.phase,
                fp_hash,
                [],
            )
            # Mark phase as completed
            output["completed_phases"] = {self.phase: True}
            # Emit plan.phase.complete
            try:
                await emit_phase_complete(
                    session_id=ctx.session_id,
                    phase=self.phase,
                    result_summary=self._get_approval_message(summary),
                    duration_s=0.0,
                    client_id=ctx.client_id,
                )
            except Exception:
                pass  # fire-and-forget
        elif decision in ("revise", "request_more"):
            output = self._process_revise(state, feedback)
        else:
            # reject (or any unknown decision)
            output = self._process_reject(state, feedback)

        return NodeExecutionResult.success(output=output)
