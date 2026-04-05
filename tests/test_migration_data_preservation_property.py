"""Property-based test for migration data preservation.

Property 13: Migration Data Preservation — For any valid v2 session state
             (flat 60+ fields), ``map_gates_to_phases`` produces a valid
             ``UnifiedSpecState`` where all original data values are preserved
             in corresponding nested phase fields.

**Validates: Requirements 21.4, 21.6**
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.migration import map_gates_to_phases


# ---------------------------------------------------------------------------
# Strategies — generate arbitrary valid v2 flat states
# ---------------------------------------------------------------------------

# Reusable atoms
_non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=80,
)

_optional_text = st.one_of(st.none(), _non_empty_text)

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

_workflow_status_st = st.sampled_from(
    ["idle", "paused", "running", "completed", "error"]
)

_current_gate_st = st.integers(min_value=1, max_value=14)

_message_st = st.fixed_dictionaries(
    {"role": st.sampled_from(["user", "assistant"]), "content": _non_empty_text}
)


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
        "workflow_status": draw(_workflow_status_st),
        "spec_session_id": draw(_non_empty_text),
        "messages": draw(st.lists(_message_st, max_size=3)),
    }
    return state


# ---------------------------------------------------------------------------
# Property 13: Migration Data Preservation
# ---------------------------------------------------------------------------


class TestMigrationDataPreservationProperty:
    """Property 13: Migration Data Preservation — For any valid v2 session
    state (flat 60+ fields), ``map_gates_to_phases`` produces a valid
    ``UnifiedSpecState`` where all original data values are preserved in
    corresponding nested phase fields.

    **Validates: Requirements 21.4, 21.6**
    """

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_context_fields_preserved(self, old_state: Dict[str, Any]):
        """All context-phase fields from the v2 state appear in
        ``new_state["context"]`` with identical values.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        assert new["context"]["spec_name"] == old_state["spec_name"]
        assert new["context"]["spec_description"] == old_state["spec_description"]
        assert new["context"]["primary_document_id"] == old_state["primary_document_id"]
        assert (
            new["context"]["primary_document_type"]
            == old_state["primary_document_type"]
        )
        assert new["context"]["user_explanation"] == old_state["user_explanation"]
        assert new["context"]["constraints"] == old_state["constraints"]
        assert new["context"]["supporting_doc_ids"] == old_state["supporting_doc_ids"]
        assert new["context"]["target_repo_id"] == old_state["target_repo_id"]

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_research_fields_preserved(self, old_state: Dict[str, Any]):
        """All research-phase fields from the v2 state appear in
        ``new_state["research"]`` with identical values.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        assert new["research"]["findings"] == old_state["research_findings"]
        # Gaps extraction: migration copies gaps from research_findings.gaps
        # when non-empty, falls back to research_gaps top-level key, or omits
        # when both are empty/falsy (default for ResearchData.gaps is []).
        old_gaps = old_state["research_findings"].get("gaps", [])
        if old_gaps:
            assert new["research"]["gaps"] == old_gaps
        else:
            # Empty gaps are not explicitly copied — default is []
            assert new["research"].get("gaps", []) == []
        assert new["research"]["gap_responses"] == old_state["gap_responses"]
        assert new["research"]["approved"] == old_state["research_approved"]
        assert (
            new["research"]["review_feedback"] == old_state["research_review_feedback"]
        )

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_plan_fields_preserved(self, old_state: Dict[str, Any]):
        """All plan-phase fields from the v2 state appear in
        ``new_state["plan"]`` with identical values.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        assert new["plan"]["roadmap"] == old_state["roadmap"]
        assert new["plan"]["feasibility"] == old_state["feasibility_assessment"]
        assert new["plan"]["approved"] == old_state["roadmap_approved"]
        assert new["plan"]["review_feedback"] == old_state["roadmap_review_feedback"]

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_decompose_fields_preserved(self, old_state: Dict[str, Any]):
        """All decompose-phase fields from the v2 state appear in
        ``new_state["decompose"]`` with identical values.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        tb = old_state["task_breakdown"]
        assert new["decompose"]["stories"] == tb["stories"]
        assert new["decompose"]["tasks"] == tb["tasks"]
        assert new["decompose"]["dependency_graph"] == tb["dependency_graph"]
        assert new["decompose"]["approved"] == old_state["tasks_approved"]
        assert new["decompose"]["review_feedback"] == old_state["tasks_review_feedback"]

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_generate_fields_preserved(self, old_state: Dict[str, Any]):
        """All generate-phase fields from the v2 state appear in
        ``new_state["generate"]`` with identical values.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        assert new["generate"]["sections"] == old_state["generated_sections"]
        assert new["generate"]["consistency_issues"] == old_state["consistency_issues"]
        assert new["generate"]["spec_document_path"] == old_state["spec_document_path"]
        assert new["generate"]["story_cards_path"] == old_state["story_cards_path"]

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_metadata_fields_preserved(self, old_state: Dict[str, Any]):
        """Workflow metadata (status, messages, session_id) is preserved.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        assert new["workflow_status"] == old_state["workflow_status"]
        assert new["messages"] == old_state["messages"]
        assert new["session_id"] == old_state["spec_session_id"]
        assert new["mode"] == "wizard"

    @given(old_state=v2_flat_state())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_output_has_valid_structure(self, old_state: Dict[str, Any]):
        """The output contains all required top-level keys of UnifiedSpecState.

        **Validates: Requirements 21.4, 21.6**
        """
        new = map_gates_to_phases(old_state)

        required_keys = {
            "context",
            "research",
            "plan",
            "decompose",
            "generate",
            "completed_phases",
            "navigation",
            "mode",
            "workflow_status",
            "messages",
            "session_id",
        }
        assert required_keys.issubset(new.keys())

        # Navigation has current_phase
        assert "current_phase" in new["navigation"]

        # completed_phases covers all 5 phases
        assert set(new["completed_phases"].keys()) == {
            "context",
            "research",
            "plan",
            "decompose",
            "generate",
        }
        for v in new["completed_phases"].values():
            assert isinstance(v, bool)
