"""Property-based test for BaseApprovalNode decision routing.

Feature: plan-feature-refactoring, Property 6: BaseApprovalNode produces correct
state transitions for all decisions

**Validates: Requirements 6.5**
"""

from __future__ import annotations

from typing import Any, Dict, List, TypedDict
from unittest.mock import AsyncMock, MagicMock, patch

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from graph_kb_api.flows.v3.models.node_models import NodeExecutionStatus
from graph_kb_api.flows.v3.nodes.plan.base_approval_node import BaseApprovalNode
from graph_kb_api.flows.v3.state.plan_state import InterruptOption


# ---------------------------------------------------------------------------
# Minimal state TypedDict for testing
# ---------------------------------------------------------------------------


class _TestState(TypedDict, total=False):
    session_id: str
    research: Dict[str, Any]
    context: Dict[str, Any]
    artifacts: Dict[str, Any]
    fingerprints: Dict[str, Any]
    completed_phases: Dict[str, bool]
    workflow_status: str
    paused_phase: str
    budget: Dict[str, Any]
    phase_data: Dict[str, Any]


# ---------------------------------------------------------------------------
# Concrete subclass implementing all abstract hooks
# ---------------------------------------------------------------------------


class _ConcreteApprovalNode(BaseApprovalNode[_TestState]):
    """Minimal concrete subclass for testing BaseApprovalNode routing."""

    phase_data_key = "phase_data"

    def __init__(self, phase: str = "research") -> None:
        self.phase = phase
        self.step_name = "approval"
        self.step_progress = 0.95
        self.node_name = "test_approval"

    def _build_summary(self, state: _TestState) -> dict[str, Any]:
        return {"spec_name": "test", "confidence": 0.9}

    def _get_approval_options(self) -> list[InterruptOption]:
        return [
            {"id": "approve", "label": "Approve"},
            {"id": "revise", "label": "Revise"},
            {"id": "reject", "label": "Reject"},
        ]

    def _get_approval_message(self, summary: dict[str, Any]) -> str:
        return "Approve this phase?"

    def _process_approve(self, state: _TestState, feedback: str) -> dict[str, Any]:
        return {
            "phase_data": {
                "approved": True,
                "approval_decision": "approve",
                "approval_feedback": feedback,
            },
        }

    def _process_revise(self, state: _TestState, feedback: str) -> dict[str, Any]:
        return {
            "phase_data": {
                "approved": False,
                "approval_decision": "revise",
                "approval_feedback": feedback,
                "needs_revision": True,
            },
        }

    def _process_reject(self, state: _TestState, feedback: str) -> dict[str, Any]:
        return {
            "phase_data": {
                "approved": False,
                "approval_decision": "reject",
                "approval_feedback": feedback,
                "rejected": True,
            },
            "workflow_status": "rejected",
            "paused_phase": self.phase,
            "error": {
                "message": "Rejected by user.",
                "code": "REJECTED",
                "phase": self.phase,
            },
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    session_id: str = "sess-1",
    phase_data: dict | None = None,
    fingerprints: dict | None = None,
) -> _TestState:
    return _TestState(
        session_id=session_id,
        research={},
        context={},
        artifacts={},
        fingerprints=fingerprints or {},
        completed_phases={},
        workflow_status="running",
        budget={},
        phase_data=phase_data or {},
    )


def _make_config() -> dict[str, Any]:
    return {
        "configurable": {
            "services": {},
            "context": None,
            "llm": None,
            "artifact_service": None,
            "client_id": "test-client",
            "progress_callback": None,
        }
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_decision_st = st.sampled_from(["approve", "reject", "revise", "request_more"])

_feedback_st = st.text(min_size=0, max_size=200)

_phase_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)

_session_id_st = st.text(min_size=1, max_size=50)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestBaseApprovalNodeDecisionRoutingProperty:
    """Feature: plan-feature-refactoring, Property 6: BaseApprovalNode produces
    correct state transitions for all decisions

    For any approval decision in {approve, reject, revise, request_more} and
    any feedback string, the BaseApprovalNode._execute_step() output should:
    set completed_phases[phase]=True and store a fingerprint on approve;
    set workflow_status="rejected" and paused_phase on reject;
    set the phase-specific revision flag on revise/request_more.

    **Validates: Requirements 6.5**
    """

    @given(
        decision=_decision_st,
        feedback=_feedback_st,
        phase=_phase_st,
        session_id=_session_id_st,
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    async def test_decision_routing_produces_correct_state_transitions(
        self,
        decision: str,
        feedback: str,
        phase: str,
        session_id: str,
    ):
        """For any decision, _execute_step routes correctly and produces
        the expected state transition keys.

        Feature: plan-feature-refactoring, Property 6: BaseApprovalNode produces
        correct state transitions for all decisions

        **Validates: Requirements 6.5**
        """
        node = _ConcreteApprovalNode(phase=phase)
        state = _make_state(session_id=session_id)
        config = _make_config()

        # Mock interrupt() to return the decision + feedback
        interrupt_response = {"decision": decision, "feedback": feedback}

        with (
            patch(
                "graph_kb_api.flows.v3.nodes.plan.base_approval_node.interrupt",
                return_value=interrupt_response,
            ),
            patch.object(
                node,
                "_load_context_items",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                node,
                "_serialize_artifacts",
                return_value=[],
            ),
            patch(
                "graph_kb_api.flows.v3.nodes.plan.base_approval_node.emit_phase_complete",
                new_callable=AsyncMock,
            ),
        ):
            result = await node._execute_step(state, config)

        assert result.status == NodeExecutionStatus.SUCCESS
        output = result.output

        if decision == "approve":
            # Must set completed_phases[phase] = True
            assert "completed_phases" in output
            assert output["completed_phases"].get(phase) is True

            # Must store a fingerprint for the phase
            assert "fingerprints" in output
            assert phase in output["fingerprints"]
            fp = output["fingerprints"][phase]
            assert fp["phase"] == phase
            assert isinstance(fp["input_hash"], str)
            assert len(fp["input_hash"]) > 0
            assert isinstance(fp["completed_at"], str)
            assert len(fp["completed_at"]) > 0

            # Phase data should reflect approval
            phase_data = output.get("phase_data", {})
            assert phase_data.get("approved") is True
            assert phase_data.get("approval_decision") == "approve"
            assert phase_data.get("approval_feedback") == feedback

        elif decision == "reject":
            # Must set workflow_status to "rejected"
            assert output.get("workflow_status") == "rejected"
            # Must set paused_phase to the current phase
            assert output.get("paused_phase") == phase

            # Phase data should reflect rejection
            phase_data = output.get("phase_data", {})
            assert phase_data.get("rejected") is True
            assert phase_data.get("approval_decision") == "reject"

            # Should NOT set completed_phases or fingerprints
            assert "completed_phases" not in output
            assert "fingerprints" not in output

        elif decision in ("revise", "request_more"):
            # Phase data should reflect revision
            phase_data = output.get("phase_data", {})
            assert phase_data.get("needs_revision") is True
            assert phase_data.get("approved") is False
            assert phase_data.get("approval_decision") == "revise"
            assert phase_data.get("approval_feedback") == feedback

            # Should NOT set completed_phases, fingerprints, or workflow_status
            assert "completed_phases" not in output
            assert "fingerprints" not in output
            assert output.get("workflow_status") != "rejected"
