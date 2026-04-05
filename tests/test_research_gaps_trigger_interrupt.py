"""Property-based test for research gaps triggering an interrupt.

Property 17: Research Gaps Trigger Interrupt — For any research result with
             non-empty ``gaps`` list, the research phase issues an
             ``interrupt()`` for gap resolution before the approval interrupt.

**Validates: Requirements 11.3**
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch, call

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.nodes.spec_phases import research_phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app_context() -> SimpleNamespace:
    """Minimal app_context with llm and graph_store attributes."""
    return SimpleNamespace(llm=object(), graph_store=object())


def _base_state(context: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a valid state with context phase completed."""
    return {
        "context": context or {"spec_name": "test-feature", "spec_description": "desc"},
        "completed_phases": {"context": True},
        "navigation": {"current_phase": "research"},
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A single gap entry — arbitrary dict with at least an id and question
_gap_entry_st = st.fixed_dictionaries(
    {
        "id": st.text(min_size=1, max_size=20),
        "question": st.text(min_size=1, max_size=100),
    },
    optional={
        "context": st.text(max_size=50),
    },
)

# Non-empty list of gaps
non_empty_gaps_st = st.lists(_gap_entry_st, min_size=1, max_size=5)

# Empty gaps (list or absent)
empty_gaps_st = st.sampled_from([[], None])


# ---------------------------------------------------------------------------
# Property 17: Research Gaps Trigger Interrupt
# ---------------------------------------------------------------------------


class TestResearchGapsTriggerInterrupt:
    """Property 17: Research Gaps Trigger Interrupt — For any research result
    with non-empty ``gaps`` list, the research phase issues an ``interrupt()``
    for gap resolution before the approval interrupt.

    **Validates: Requirements 11.3**
    """

    @given(gaps=non_empty_gaps_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_non_empty_gaps_trigger_two_interrupts(
        self,
        gaps: List[Dict[str, Any]],
    ):
        """When run_research returns non-empty gaps, interrupt() is called
        at least twice: first for gap resolution, then for approval.

        **Validates: Requirements 11.3**
        """
        findings = {
            "codebase": {},
            "documents": {},
            "risks": [],
            "gaps": gaps,
            "summary": "test summary",
            "confidence_score": 0.8,
        }

        interrupt_calls: List[Dict[str, Any]] = []

        def mock_interrupt(value: Any) -> Dict[str, Any]:
            interrupt_calls.append(value)
            # Return gap responses for the first call, approval for the second
            if len(interrupt_calls) == 1:
                # Gap resolution response
                return {"gap_1": "resolved"}
            # Approval response
            return {"approved": True, "feedback": ""}

        with (
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.run_research",
                new_callable=AsyncMock,
                return_value=findings,
            ),
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.interrupt",
                side_effect=mock_interrupt,
            ),
        ):
            result = await research_phase(_base_state(), _app_context())

        # Must have been called exactly 2 times
        assert len(interrupt_calls) == 2, (
            f"Expected 2 interrupt() calls (gap resolution + approval) "
            f"when gaps are present, got {len(interrupt_calls)}"
        )

        # First interrupt should contain the gaps for resolution
        first_call = interrupt_calls[0]
        assert "gaps" in first_call, (
            "First interrupt() call should contain 'gaps' for gap resolution"
        )
        assert first_call["gaps"] == gaps, (
            "First interrupt() should pass the exact gaps from findings"
        )

        # Second interrupt should be for approval
        second_call = interrupt_calls[1]
        assert second_call.get("action") == "approve_or_reject", (
            "Second interrupt() call should be the approval interrupt "
            f"with action='approve_or_reject', got {second_call}"
        )

    @given(empty_gaps=empty_gaps_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_empty_gaps_trigger_single_interrupt(
        self,
        empty_gaps: Any,
    ):
        """When run_research returns empty or absent gaps, interrupt() is
        called exactly once for approval only.

        **Validates: Requirements 11.3**
        """
        findings: Dict[str, Any] = {
            "codebase": {},
            "documents": {},
            "risks": [],
            "summary": "test summary",
            "confidence_score": 0.8,
        }
        if empty_gaps is not None:
            findings["gaps"] = empty_gaps

        interrupt_calls: List[Dict[str, Any]] = []

        def mock_interrupt(value: Any) -> Dict[str, Any]:
            interrupt_calls.append(value)
            return {"approved": True, "feedback": ""}

        with (
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.run_research",
                new_callable=AsyncMock,
                return_value=findings,
            ),
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.interrupt",
                side_effect=mock_interrupt,
            ),
        ):
            result = await research_phase(_base_state(), _app_context())

        # Must have been called exactly 1 time (approval only)
        assert len(interrupt_calls) == 1, (
            f"Expected 1 interrupt() call (approval only) when gaps are "
            f"empty/absent, got {len(interrupt_calls)}"
        )

        # The single interrupt should be for approval
        assert interrupt_calls[0].get("action") == "approve_or_reject", (
            "The only interrupt() call should be the approval interrupt"
        )

    @given(gaps=non_empty_gaps_st)
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_gap_resolution_happens_before_approval(
        self,
        gaps: List[Dict[str, Any]],
    ):
        """The gap resolution interrupt is issued strictly before the
        approval interrupt — ordering is enforced.

        **Validates: Requirements 11.3**
        """
        findings = {
            "codebase": {},
            "documents": {},
            "risks": [],
            "gaps": gaps,
            "summary": "summary",
            "confidence_score": 0.5,
        }

        call_order: List[str] = []

        def mock_interrupt(value: Any) -> Dict[str, Any]:
            if "gaps" in value and value.get("action") != "approve_or_reject":
                call_order.append("gap_resolution")
                return {"gap_1": "answer"}
            else:
                call_order.append("approval")
                return {"approved": True, "feedback": ""}

        with (
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.run_research",
                new_callable=AsyncMock,
                return_value=findings,
            ),
            patch(
                "graph_kb_api.flows.v3.nodes.spec_phases.interrupt",
                side_effect=mock_interrupt,
            ),
        ):
            await research_phase(_base_state(), _app_context())

        assert call_order == ["gap_resolution", "approval"], (
            f"Expected gap_resolution before approval, got {call_order}"
        )
