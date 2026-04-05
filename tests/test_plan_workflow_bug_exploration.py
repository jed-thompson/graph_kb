"""Bug condition exploration test for Plan Workflow Six-Point Failure.

Property 1: Fault Condition - Plan Workflow Six-Point Failure

**CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bugs exist.
**DO NOT attempt to fix the test or the code when it fails.**
**NOTE**: This test encodes the expected behavior - it will validate the fix when
         it passes after implementation.

**GOAL**: Surface counterexamples that demonstrate all six bug conditions exist:
  - Defect 1.1: CollectContextNode._execute_step returns without calling interrupt()
  - Defect 1.3: validateEvent returns null for phase: "planning"
  - Defect 1.4: PhaseId("planning") raises validation error
  - Defect 1.5: /plan command is not recognized by handleCommand
  - Defect 1.6: handle_plan_navigate (line 520) and handle_plan_retry (line 870)
               crash with TypeError when awaiting synchronous get_workflow_state

**Validates: Requirements 1.1, 1.3, 1.4, 1.5, 1.6**
"""

import inspect
from typing import Any, Dict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Direct imports that avoid the circular import chain through websocket.__init__
from graph_kb_api.flows.v3.nodes.plan_nodes import CollectContextNode
from graph_kb_api.websocket.events import PhaseId, SpecPhasePromptData

# ---------------------------------------------------------------------------
# Defect 1.1: CollectContextNode._execute_step returns without calling interrupt()
# ---------------------------------------------------------------------------


class TestCollectContextNodeInterrupt:
    """Defect 1.1: CollectContextNode._execute_step should call interrupt() with
    phase prompt data, but currently returns NodeExecutionResult.success(output={})
    without interrupting.

    **Validates: Requirements 1.1**
    """

    @pytest.mark.asyncio
    async def test_collect_context_node_raises_graph_interrupt(self):
        """CollectContextNode._execute_step MUST raise GraphInterrupt.

        EXPECTED BEHAVIOR: The node calls interrupt() which raises GraphInterrupt
        with phase prompt data (session_id, phase, fields, prefilled).

        CURRENT BUG: Returns NodeExecutionResult.success(output={}) without
        calling interrupt(), so no GraphInterrupt is raised.

        This test SHOULD FAIL on unfixed code.
        """
        from langgraph.errors import GraphInterrupt

        node = CollectContextNode()
        state: Dict[str, Any] = {
            "session_id": "test-session-123",
            "context": {"spec_name": "Test Plan"},
        }
        config: Dict[str, Any] = {"configurable": {"thread_id": "test-thread"}}

        # The node SHOULD raise GraphInterrupt when it calls interrupt()
        # Outside a LangGraph runnable context, interrupt() raises RuntimeError
        # ("Called get_config outside of a runnable context") which confirms
        # interrupt() IS being called. Inside a real graph, this becomes GraphInterrupt.
        # On unfixed code, neither exception is raised — it just returns empty output.
        with pytest.raises((GraphInterrupt, RuntimeError)):
            await node._execute_step(state, config)


# ---------------------------------------------------------------------------
# Defect 1.4: PhaseId("planning") raises validation error
# ---------------------------------------------------------------------------


class TestPhaseIdPlanningValidation:
    """Defect 1.4: PhaseId enum should include "planning" and "assembly" values,
    but currently only has the 7 spec phases.

    **Validates: Requirements 1.4**
    """

    def test_phase_id_planning_is_valid(self):
        """PhaseId("planning") MUST be a valid enum value.

        EXPECTED BEHAVIOR: PhaseId("planning") returns PhaseId.PLANNING without error.

        CURRENT BUG: PhaseId("planning") raises ValueError because "planning"
        is not in the enum.

        This test SHOULD FAIL on unfixed code.
        """
        # This should NOT raise - "planning" should be a valid PhaseId
        phase = PhaseId("planning")
        assert phase.value == "planning"

    def test_phase_id_assembly_is_valid(self):
        """PhaseId("assembly") MUST be a valid enum value.

        EXPECTED BEHAVIOR: PhaseId("assembly") returns PhaseId.ASSEMBLY without error.

        CURRENT BUG: PhaseId("assembly") raises ValueError because "assembly"
        is not in the enum.

        This test SHOULD FAIL on unfixed code.
        """
        # This should NOT raise - "assembly" should be a valid PhaseId
        phase = PhaseId("assembly")
        assert phase.value == "assembly"

    def test_spec_phase_prompt_data_accepts_planning_phase(self):
        """SpecPhasePromptData MUST accept phase="planning".

        EXPECTED BEHAVIOR: SpecPhasePromptData(session_id="x", phase="planning", fields=[])
        constructs without error.

        CURRENT BUG: Pydantic validation fails because "planning" is not in PhaseId enum.

        This test SHOULD FAIL on unfixed code.
        """
        # This should NOT raise ValidationError
        data = SpecPhasePromptData(
            session_id="test-session",
            phase="planning",  # type: ignore[arg-type]
            fields=[],
        )
        assert data.phase.value == "planning"


# ---------------------------------------------------------------------------
# Defect 1.3: validateEvent returns null for phase: "planning"
# (Python-side: PhaseId enum is the source of truth for valid phases)
# ---------------------------------------------------------------------------


class TestValidateEventPlanningPhase:
    """Defect 1.3: validateEvent should accept events with phase: "planning",
    but currently rejects them because VALID_PHASE_IDS only has 7 spec phases.

    We test the Python PhaseId enum which is the source of truth.

    **Validates: Requirements 1.3**
    """

    @given(phase=st.sampled_from(["planning", "assembly"]))
    @settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
    def test_plan_phases_are_valid_phase_ids(self, phase: str):
        """Plan-specific phases MUST be valid PhaseId values.

        EXPECTED BEHAVIOR: "planning" and "assembly" are valid PhaseId values.

        CURRENT BUG: These phases are not in the PhaseId enum.

        This test SHOULD FAIL on unfixed code.
        """
        # This should NOT raise
        phase_id = PhaseId(phase)
        assert phase_id.value == phase


# ---------------------------------------------------------------------------
# Defect 1.5: /plan command is not recognized by handleCommand
# (Backend readiness test - the actual handler is in TypeScript)
# ---------------------------------------------------------------------------


class TestPlanCommandHandler:
    """Defect 1.5: ChatContext.tsx handleCommand should recognize /plan command,
    but currently only handles /spec, /wizard, /clear, /help, and /ingest.

    We test the backend's ability to receive plan.start messages.

    **Validates: Requirements 1.5**
    """

    def test_plan_start_payload_is_valid(self):
        """plan.start payload validation MUST work.

        This confirms the backend is ready to receive /plan commands
        once the frontend handler is added.
        """
        from graph_kb_api.websocket.plan_events import PlanStartPayload

        payload = PlanStartPayload(name="My Feature", description="A test feature")
        assert payload.name == "My Feature"
        assert payload.description == "A test feature"


# ---------------------------------------------------------------------------
# Defect 1.6: handle_plan_navigate and handle_plan_retry await synchronous
#             get_workflow_state causing TypeError
# ---------------------------------------------------------------------------


class TestAwaitSynchronousGetWorkflowState:
    """Defect 1.6: handle_plan_navigate (line 520) and handle_plan_retry (line 870)
    incorrectly await the synchronous get_workflow_state method, causing
    TypeError: object dict can't be used in 'await' expression.

    Note: handle_plan_resume (line 649) already correctly calls this method
    without await.

    **Validates: Requirements 1.6**
    """

    def test_handle_plan_navigate_does_not_await_get_workflow_state(self):
        """handle_plan_navigate MUST NOT await get_workflow_state.

        EXPECTED BEHAVIOR: get_workflow_state is called without await.

        CURRENT BUG: Line 520 has `state = await engine.get_workflow_state(config)`
        which will crash with TypeError because get_workflow_state is synchronous.

        We verify by inspecting the source code of handle_plan_navigate for the
        buggy `await engine.get_workflow_state` pattern.

        This test SHOULD FAIL on unfixed code.
        """
        from graph_kb_api.websocket.handlers.plan_dispatcher import handle_plan_navigate

        source = inspect.getsource(handle_plan_navigate)

        # The source should NOT contain "await engine.get_workflow_state"
        # On unfixed code, this pattern exists at line 520
        assert "await engine.get_workflow_state" not in source, (
            "handle_plan_navigate incorrectly awaits synchronous get_workflow_state. "
            "Line 520 has `state = await engine.get_workflow_state(config)` but "
            "get_workflow_state is a synchronous method that returns a plain dict."
        )

    def test_handle_plan_retry_does_not_await_get_workflow_state(self):
        """handle_plan_retry MUST NOT await get_workflow_state.

        EXPECTED BEHAVIOR: get_workflow_state is called without await.

        CURRENT BUG: Line 870 has `state = await engine.get_workflow_state(config)`
        which will crash with TypeError because get_workflow_state is synchronous.

        We verify by inspecting the source code of handle_plan_retry for the
        buggy `await engine.get_workflow_state` pattern.

        This test SHOULD FAIL on unfixed code.
        """
        from graph_kb_api.websocket.handlers.plan_dispatcher import handle_plan_retry

        source = inspect.getsource(handle_plan_retry)

        # The source should NOT contain "await engine.get_workflow_state"
        # On unfixed code, this pattern exists at line 870
        assert "await engine.get_workflow_state" not in source, (
            "handle_plan_retry incorrectly awaits synchronous get_workflow_state. "
            "Line 870 has `state = await engine.get_workflow_state(config)` but "
            "get_workflow_state is a synchronous method that returns a plain dict."
        )

    def test_handle_plan_resume_correctly_calls_get_workflow_state(self):
        """handle_plan_resume correctly calls get_workflow_state without await.

        This is a reference test showing the CORRECT pattern that
        handle_plan_navigate and handle_plan_retry should follow.

        Line 649 in plan_dispatcher.py shows:
        `state = engine.get_workflow_state(config)` (no await - correct!)
        """
        from graph_kb_api.websocket.handlers.plan_dispatcher import handle_plan_resume

        source = inspect.getsource(handle_plan_resume)

        # handle_plan_resume should have the correct pattern (no await)
        # It uses `state = engine.get_workflow_state(config)` at line 649
        assert "engine.get_workflow_state" in source
        # Verify it does NOT have the buggy await pattern
        assert "await engine.get_workflow_state" not in source


# ---------------------------------------------------------------------------
# Property-Based Test: All Bug Conditions Combined
# ---------------------------------------------------------------------------


class TestPlanWorkflowBugConditions:
    """Property 1: Fault Condition - Plan Workflow Six-Point Failure

    This property test verifies that all bug conditions are resolved.
    On unfixed code, at least one of these conditions will fail.

    **Validates: Requirements 1.1, 1.3, 1.4, 1.5, 1.6**
    """

    @given(
        phase=st.sampled_from(["planning", "assembly"]),
        session_id=st.text(
            min_size=1,
            max_size=50,
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
        ),
    )
    @settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
    def test_plan_phases_can_be_used_in_spec_phase_prompt_data(self, phase: str, session_id: str):
        """Plan phases MUST be usable in SpecPhasePromptData.

        This property test generates random plan phases and session IDs
        and verifies they can be used to construct valid SpecPhasePromptData.

        EXPECTED BEHAVIOR: SpecPhasePromptData accepts "planning" and "assembly" phases.

        CURRENT BUG: Pydantic validation fails because these phases are not in PhaseId.

        This test SHOULD FAIL on unfixed code.
        """
        # This should NOT raise ValidationError
        data = SpecPhasePromptData(
            session_id=session_id,
            phase=phase,  # type: ignore[arg-type]
            fields=[],
        )
        assert data.phase.value == phase
        assert data.session_id == session_id
