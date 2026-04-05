"""Property-based test for migration refusing active sessions.

Property 14: Migration Refuses Active Sessions — For any session with
             ``workflow_status`` of ``running`` or ``completed``,
             ``migrate_session`` returns ``false`` and leaves session
             state unchanged.

**Validates: Requirements 21.5**
"""

from __future__ import annotations

import copy
from typing import Any, Dict

from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.migration import migrate_session


# ---------------------------------------------------------------------------
# Strategies — reuse atoms from the data-preservation test
# ---------------------------------------------------------------------------

_non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=80,
)

_json_value = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(allow_nan=False, allow_infinity=False),
        _non_empty_text,
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.dictionaries(_non_empty_text, children, max_size=3),
    ),
    max_leaves=10,
)

_json_dict = st.dictionaries(_non_empty_text, _json_value, max_size=4)

_string_list = st.lists(_non_empty_text, max_size=5)

_gap_st = st.fixed_dictionaries(
    {
        "id": _non_empty_text,
        "question": _non_empty_text,
        "context": _non_empty_text,
    }
)

_story_st = st.fixed_dictionaries(
    {
        "id": _non_empty_text,
        "title": _non_empty_text,
        "description": _non_empty_text,
        "acceptance_criteria": st.lists(
            st.fixed_dictionaries(
                {"id": _non_empty_text, "description": _non_empty_text}
            ),
            min_size=1,
            max_size=3,
        ),
        "story_points": st.integers(min_value=1, max_value=21),
    }
)

_task_st = st.fixed_dictionaries(
    {
        "id": _non_empty_text,
        "story_id": _non_empty_text,
        "title": _non_empty_text,
    }
)

_gate_status_values = st.sampled_from(["pending", "in_progress", "complete", "skipped"])

_gate_status_st = st.fixed_dictionaries(
    {str(i): _gate_status_values for i in range(1, 15)}
)

_current_gate_st = st.integers(min_value=1, max_value=14)

_message_st = st.fixed_dictionaries(
    {"role": st.sampled_from(["user", "assistant"]), "content": _non_empty_text}
)

# The key strategy: only non-migratable statuses
_non_migratable_status_st = st.sampled_from(["running", "completed"])


@st.composite
def v2_flat_state(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid v2 flat session state with 60+ fields."""
    gaps = draw(st.lists(_gap_st, max_size=3))

    research_findings = {
        "codebase": draw(_json_dict),
        "documents": draw(_json_dict),
        "risks": draw(st.lists(_json_dict, max_size=3)),
        "gaps": gaps,
        "summary": draw(_non_empty_text),
        "confidence_score": draw(st.floats(min_value=0.0, max_value=1.0)),
    }

    stories = draw(st.lists(_story_st, min_size=1, max_size=4))
    tasks = draw(st.lists(_task_st, max_size=5))
    dep_graph = {s["id"]: [] for s in stories}
    task_breakdown = {
        "stories": stories,
        "tasks": tasks,
        "dependency_graph": dep_graph,
    }

    state: Dict[str, Any] = {
        # Context fields (Gates 1-5)
        "spec_name": draw(_non_empty_text),
        "spec_description": draw(_non_empty_text),
        "primary_document_id": draw(_non_empty_text),
        "primary_document_type": draw(st.sampled_from(["upload", "url", "paste"])),
        "user_explanation": draw(_non_empty_text),
        "constraints": draw(_json_dict),
        "supporting_doc_ids": draw(_string_list),
        "target_repo_id": draw(_non_empty_text),
        # Research fields (Gates 6-7)
        "research_findings": research_findings,
        "research_approved": draw(st.booleans()),
        "research_review_feedback": draw(_non_empty_text),
        "gap_responses": {g["id"]: draw(_non_empty_text) for g in gaps},
        # Plan fields (Gates 8-9)
        "roadmap": draw(_json_dict),
        "roadmap_approved": draw(st.booleans()),
        "roadmap_review_feedback": draw(_non_empty_text),
        "feasibility_assessment": draw(_json_dict),
        # Decompose fields (Gates 10-11)
        "task_breakdown": task_breakdown,
        "tasks_approved": draw(st.booleans()),
        "tasks_review_feedback": draw(_non_empty_text),
        # Generate fields (Gates 12-14)
        "generated_sections": draw(
            st.dictionaries(_non_empty_text, _non_empty_text, max_size=5)
        ),
        "consistency_issues": draw(st.lists(_json_dict, max_size=3)),
        "spec_document_path": draw(_non_empty_text),
        "story_cards_path": draw(_non_empty_text),
        # Navigation / meta
        "current_gate": draw(_current_gate_st),
        "gate_status": draw(_gate_status_st),
        "workflow_status": draw(_non_migratable_status_st),
        "spec_session_id": draw(_non_empty_text),
        "messages": draw(st.lists(_message_st, max_size=3)),
    }
    return state


# ---------------------------------------------------------------------------
# Property 14: Migration Refuses Active Sessions
# ---------------------------------------------------------------------------


class TestMigrationRefusesActiveSessionsProperty:
    """Property 14: Migration Refuses Active Sessions — For any session with
    ``workflow_status`` of ``running`` or ``completed``, ``migrate_session``
    returns ``false`` and leaves session state unchanged.

    **Validates: Requirements 21.5**
    """

    @given(state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_migrate_returns_false_for_active_sessions(self, state: Dict[str, Any]):
        """``migrate_session`` returns ``False`` for sessions with
        ``workflow_status`` of ``running`` or ``completed``.

        **Validates: Requirements 21.5**
        """
        session = {
            "workflow_status": state["workflow_status"],
            "state": state,
            "engine_version": "v2_gates",
        }

        result = migrate_session(session)

        assert result is False

    @given(state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_session_state_unchanged_after_refusal(self, state: Dict[str, Any]):
        """When migration is refused, the session dict is not mutated —
        ``state``, ``engine_version``, and ``workflow_status`` remain
        identical to their pre-call values.

        **Validates: Requirements 21.5**
        """
        session = {
            "workflow_status": state["workflow_status"],
            "state": state,
            "engine_version": "v2_gates",
        }

        # Deep copy to compare after the call
        session_before = copy.deepcopy(session)

        migrate_session(session)

        assert session == session_before
