"""Property-based tests for StatePrunerNode.

Property 17: State boundedness — For any sequence of operations, accumulating
fields remain bounded after pruning (gaps_detected ≤ active_gap_count,
progress_events ≤ 10).

**Validates: Requirements 12.1, 12.4, 12.5**
"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.state_pruner_node import (
    MAX_PROGRESS_EVENTS,
    StatePrunerNode,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def gap_info(draw: st.DrawFn):
    """Generate a single GapInfo-like dict with a resolved flag."""
    resolved = draw(st.booleans())
    return {
        "gap_id": draw(st.from_regex(r"gap_[a-z0-9]{3,8}", fullmatch=True)),
        "section_id": draw(st.from_regex(r"sec_[a-z0-9]{2,6}", fullmatch=True)),
        "gap_type": draw(
            st.sampled_from(
                [
                    "missing_requirement",
                    "ambiguous",
                    "conflicting",
                    "empty_kb_result",
                    "missing_doc_ref",
                ]
            )
        ),
        "description": draw(st.text(min_size=1, max_size=50)),
        "question": draw(st.text(min_size=1, max_size=50)),
        "context": draw(st.text(min_size=0, max_size=30)),
        "source": draw(st.sampled_from(["proactive", "reviewer", "agent"])),
        "resolved": resolved,
        "resolution": draw(st.text(min_size=1, max_size=30)) if resolved else None,
    }


@st.composite
def gaps_detected_dict(draw: st.DrawFn):
    """Generate a gaps_detected dict with a mix of resolved and unresolved gaps."""
    n = draw(st.integers(min_value=0, max_value=30))
    gaps = {}
    for i in range(n):
        g = draw(gap_info())
        gid = f"gap_{i:03d}"
        g["gap_id"] = gid
        gaps[gid] = g
    return gaps


@st.composite
def progress_events_list(draw: st.DrawFn):
    """Generate a list of progress events of varying length."""
    n = draw(st.integers(min_value=0, max_value=50))
    events = []
    for i in range(n):
        events.append(
            {
                "event_type": draw(
                    st.sampled_from(
                        [
                            "task_started",
                            "task_completed",
                            "rework_requested",
                            "gap_detected",
                            "awaiting_approval",
                            "workflow_complete",
                        ]
                    )
                ),
                "message": f"Event {i}",
                "task_id": f"task_{i:03d}",
                "section_title": f"Section {i}",
                "progress_pct": draw(st.floats(min_value=0.0, max_value=1.0)),
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )
    return events


@st.composite
def pruner_state(draw: st.DrawFn):
    """Generate a full state dict suitable for the StatePrunerNode."""
    gaps = draw(gaps_detected_dict())
    events = draw(progress_events_list())

    # Agent execution fields that should be cleared
    agent_draft = draw(st.one_of(st.none(), st.text(min_size=1, max_size=100)))
    confidence_score = draw(
        st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0))
    )
    confidence_rationale = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))
    review_feedback = draw(st.one_of(st.none(), st.text(min_size=1, max_size=100)))
    review_verdict = draw(
        st.one_of(
            st.none(),
            st.sampled_from(["approved", "rework_needed", "gap_detected"]),
        )
    )

    return {
        "gaps_detected": gaps,
        "progress_events": events,
        "agent_draft": agent_draft,
        "confidence_score": confidence_score,
        "confidence_rationale": confidence_rationale,
        "review_feedback": review_feedback,
        "review_verdict": review_verdict,
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestStateBoundedness:
    """Property 17: State boundedness — For any sequence of operations,
    accumulating fields remain bounded after pruning.

    After the StatePrunerNode runs:
      - gaps_detected contains only unresolved gaps (≤ active gap count)
      - progress_events has at most MAX_PROGRESS_EVENTS entries
      - Stale agent execution fields are cleared

    **Validates: Requirements 12.1, 12.4, 12.5**
    """

    @given(state=pruner_state())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_progress_events_bounded(self, state):
        """After pruning, progress_events has at most MAX_PROGRESS_EVENTS entries."""
        node = StatePrunerNode()
        result = await node(state)

        assert len(result["progress_events"]) <= MAX_PROGRESS_EVENTS, (
            f"progress_events has {len(result['progress_events'])} entries, "
            f"expected at most {MAX_PROGRESS_EVENTS}"
        )

    @given(state=pruner_state())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_gaps_bounded_to_active_count(self, state):
        """After pruning, gaps_detected contains only unresolved gaps."""
        node = StatePrunerNode()
        result = await node(state)

        # Count active (unresolved) gaps in the original state
        original_gaps = state.get("gaps_detected", {})
        active_count = sum(
            1 for g in original_gaps.values() if not g.get("resolved", False)
        )

        pruned_gaps = result["gaps_detected"]
        assert len(pruned_gaps) == active_count, (
            f"Expected {active_count} active gaps, got {len(pruned_gaps)}"
        )

        # Every remaining gap must be unresolved
        for gid, gap in pruned_gaps.items():
            assert not gap.get("resolved", False), (
                f"Gap '{gid}' is resolved but was not removed by pruning"
            )

    @given(state=pruner_state())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_stale_agent_fields_cleared(self, state):
        """After pruning, stale agent execution fields are set to None."""
        node = StatePrunerNode()
        result = await node(state)

        assert result["agent_draft"] is None
        assert result["confidence_score"] is None
        assert result["confidence_rationale"] is None
        assert result["review_feedback"] is None
        assert result["review_verdict"] is None

    @given(state=pruner_state())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @pytest.mark.asyncio
    async def test_progress_events_preserve_most_recent(self, state):
        """Pruning keeps the most recent events (tail of the list)."""
        node = StatePrunerNode()
        result = await node(state)

        original_events = state.get("progress_events", []) or []
        pruned_events = result["progress_events"]

        if len(original_events) > MAX_PROGRESS_EVENTS:
            expected = original_events[-MAX_PROGRESS_EVENTS:]
            assert pruned_events == expected, (
                "Pruned events should be the last MAX_PROGRESS_EVENTS entries"
            )
        else:
            assert pruned_events == list(original_events), (
                "When under the limit, all events should be preserved"
            )
