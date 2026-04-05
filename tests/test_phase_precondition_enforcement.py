"""Property-based test for phase precondition enforcement.

Property 10: Phase Precondition Enforcement — For any phase requiring
             upstream approval (plan requires research.approved, orchestrate
             requires plan.approved, generate requires all upstream complete
             + orchestrate.task_results non-empty), the phase function does
             not proceed if precondition is unmet.

**Validates: Requirements 12.4, 13.5, 14.5**
"""

from __future__ import annotations

from types import SimpleNamespace

from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dummy_app_context() -> SimpleNamespace:
    """Minimal app_context with llm and graph_store attributes.

    The phase functions should raise *before* touching these, so they
    can be plain sentinels.
    """
    return SimpleNamespace(llm=None, graph_store=None)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# research.approved is either missing, False, or a non-bool falsy value
research_not_approved_st = st.fixed_dictionaries(
    {},
    optional={
        "approved": st.sampled_from([False, None, 0, ""]),
        "findings": st.just({}),
        "review_feedback": st.text(max_size=50),
    },
)

# plan.approved is either missing, False, or a non-bool falsy value
plan_not_approved_st = st.fixed_dictionaries(
    {},
    optional={
        "approved": st.sampled_from([False, None, 0, ""]),
        "roadmap": st.just({}),
        "review_feedback": st.text(max_size=50),
    },
)

# For generate_phase: at least one upstream phase is not complete
# generate_phase checks: context, research, plan, orchestrate, completeness
_required_phases = ["context", "research", "plan", "orchestrate", "completeness"]


@st.composite
def incomplete_upstream_st(draw: st.DrawFn) -> Dict[str, bool]:
    """Generate a completed_phases dict where at least one required
    upstream phase is not True."""
    phases: Dict[str, bool] = {}
    for p in _required_phases:
        phases[p] = draw(st.booleans())

    # Ensure at least one is False
    if all(phases.get(p) for p in _required_phases):
        # Force one to be False
        target = draw(st.sampled_from(_required_phases))
        phases[target] = False

    return phases


# ---------------------------------------------------------------------------
# Property 10: Phase Precondition Enforcement
# ---------------------------------------------------------------------------


class TestPhasePreconditionEnforcement:
    """Property 10: Phase Precondition Enforcement — For any phase
    requiring upstream approval, the phase function does not proceed
    if the precondition is unmet.

    **Validates: Requirements 12.4, 13.5, 14.5**
    """

    # ── plan_phase: requires research.approved == True ───────────

    @given(research=research_not_approved_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_plan_phase_rejects_unapproved_research(
        self, research: Dict[str, Any]
    ):
        """plan_phase raises ValueError when research.approved is not True.

        **Validates: Requirements 12.4**
        """
        state: Dict[str, Any] = {
            "context": {"spec_name": "test", "user_explanation": "test"},
            "research": research,
            "completed_phases": {"context": True, "review": True, "research": True},
            "navigation": {"current_phase": "plan"},
        }

        with pytest.raises(ValueError, match="research.*approved"):
            await plan_phase(state, _dummy_app_context())

    # ── orchestrate_phase: requires plan.approved == True ─────────

    @given(plan=plan_not_approved_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_orchestrate_phase_rejects_unapproved_plan(
        self, plan: Dict[str, Any]
    ):
        """orchestrate_phase raises ValueError when plan.approved is not True.

        **Validates: Requirements 13.5**
        """
        state: Dict[str, Any] = {
            "context": {"spec_name": "test", "user_explanation": "test"},
            "research": {"approved": True, "findings": {}},
            "plan": plan,
            "completed_phases": {
                "context": True,
                "review": True,
                "research": True,
                "plan": True,
            },
            "navigation": {"current_phase": "orchestrate"},
        }

        with pytest.raises(ValueError, match="plan.*approved"):
            await orchestrate_phase(state, _dummy_app_context())

    # ── generate_phase: requires all upstream complete ───────────

    @given(completed=incomplete_upstream_st())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_generate_phase_rejects_incomplete_upstream(
        self, completed: Dict[str, bool]
    ):
        """generate_phase raises ValueError when any upstream phase is
        not marked complete in completed_phases.

        **Validates: Requirements 14.5**
        """
        state: Dict[str, Any] = {
            "context": {"spec_name": "test"},
            "research": {"approved": True},
            "plan": {"approved": True},
            "orchestrate": {
                "task_results": [{"task_id": "t1", "status": "approved"}],
                "all_complete": True,
            },
            "completeness": {"complete": True},
            "generate": {},
            "completed_phases": completed,
            "navigation": {"current_phase": "generate"},
        }

        with pytest.raises(ValueError, match="upstream phases"):
            await generate_phase(state, _dummy_app_context())

    # ── generate_phase: requires orchestrate.task_results non-empty ──

    @given(task_results=st.just([]))
    @settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_generate_phase_rejects_empty_task_results(
        self,
        task_results: list,
    ):
        """generate_phase raises ValueError when orchestrate.task_results
        is empty, even if all upstream phases are marked complete.

        **Validates: Requirements 14.5**
        """
        state: Dict[str, Any] = {
            "context": {"spec_name": "test"},
            "research": {"approved": True},
            "plan": {"approved": True},
            "orchestrate": {"task_results": task_results, "all_complete": True},
            "completeness": {"complete": True},
            "generate": {},
            "completed_phases": {
                "context": True,
                "review": True,
                "research": True,
                "plan": True,
                "orchestrate": True,
                "completeness": True,
            },
            "navigation": {"current_phase": "generate"},
        }

        with pytest.raises(ValueError, match="task_results.*non-empty"):
            await generate_phase(state, _dummy_app_context())
