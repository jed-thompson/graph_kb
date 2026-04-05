"""Property-based test for decompose story completeness.

Property 21: Decompose Story Completeness — For any story in ``run_decompose``
             result, it contains ``id``, ``title``, ``description``,
             ``acceptance_criteria``, and ``story_points``.

**Validates: Requirements 13.4**

Since ``run_decompose`` is currently a stub (raises NotImplementedError),
these tests validate the *contract* that any story dict returned by
``run_decompose`` must satisfy.  A helper ``check_story_completeness``
encodes the invariant and is exercised with Hypothesis-generated data.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings, HealthCheck, strategies as st


# ---------------------------------------------------------------------------
# Contract helper
# ---------------------------------------------------------------------------


def check_story_completeness(story: Dict[str, Any]) -> None:
    """Assert that a story satisfies the completeness contract.

    Each story must have:
    - ``id``: str
    - ``title``: str
    - ``description``: str
    - ``acceptance_criteria``: list
    - ``story_points``: positive int (> 0)

    Raises ``AssertionError`` if any required field is missing or has the
    wrong type.
    """
    # id checks
    assert "id" in story, "story must contain 'id'"
    assert isinstance(story["id"], str), (
        f"story 'id' must be a str, got {type(story['id']).__name__}"
    )

    # title checks
    assert "title" in story, "story must contain 'title'"
    assert isinstance(story["title"], str), (
        f"story 'title' must be a str, got {type(story['title']).__name__}"
    )

    # description checks
    assert "description" in story, "story must contain 'description'"
    assert isinstance(story["description"], str), (
        f"story 'description' must be a str, got {type(story['description']).__name__}"
    )

    # acceptance_criteria checks
    assert "acceptance_criteria" in story, "story must contain 'acceptance_criteria'"
    assert isinstance(story["acceptance_criteria"], list), (
        f"story 'acceptance_criteria' must be a list, "
        f"got {type(story['acceptance_criteria']).__name__}"
    )

    # story_points checks
    assert "story_points" in story, "story must contain 'story_points'"
    sp = story["story_points"]
    assert isinstance(sp, int) and not isinstance(sp, bool), (
        f"story 'story_points' must be an int, got {type(sp).__name__}"
    )
    assert sp > 0, f"story 'story_points' must be positive, got {sp}"


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid story fields
valid_id_st = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Pd"),
    ),
)
valid_title_st = st.text(min_size=1, max_size=100)
valid_description_st = st.text(min_size=1, max_size=500)
valid_acceptance_criteria_st = st.lists(
    st.text(min_size=1, max_size=100), min_size=0, max_size=10
)
valid_story_points_st = st.integers(min_value=1, max_value=100)


@st.composite
def valid_story_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid story dict with all required fields."""
    return {
        "id": draw(valid_id_st),
        "title": draw(valid_title_st),
        "description": draw(valid_description_st),
        "acceptance_criteria": draw(valid_acceptance_criteria_st),
        "story_points": draw(valid_story_points_st),
    }


REQUIRED_FIELDS = ["id", "title", "description", "acceptance_criteria", "story_points"]


@st.composite
def story_missing_field_st(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a story dict with exactly one required field removed."""
    story = draw(valid_story_st())
    field_to_remove = draw(st.sampled_from(REQUIRED_FIELDS))
    del story[field_to_remove]
    return story


# ---------------------------------------------------------------------------
# Property 21: Decompose Story Completeness
# ---------------------------------------------------------------------------


class TestDecomposeStoryCompleteness:
    """Property 21: Decompose Story Completeness — For any story in
    ``run_decompose`` result, it contains ``id``, ``title``,
    ``description``, ``acceptance_criteria``, and ``story_points``.

    **Validates: Requirements 13.4**
    """

    @given(story=valid_story_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_valid_stories_pass_check(self, story: Dict[str, Any]):
        """Any story with all required fields and correct types passes.

        **Validates: Requirements 13.4**
        """
        check_story_completeness(story)

    @given(story=story_missing_field_st())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_story_missing_any_field_fails(self, story: Dict[str, Any]):
        """A story missing any single required field fails the check.

        **Validates: Requirements 13.4**
        """
        with pytest.raises(AssertionError, match="must contain"):
            check_story_completeness(story)

    @given(
        bad_id=st.one_of(st.integers(), st.none(), st.booleans(), st.lists(st.text()))
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_string_id_fails(self, bad_id: Any):
        """A non-string ``id`` fails the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": bad_id,
            "title": "Title",
            "description": "Desc",
            "acceptance_criteria": [],
            "story_points": 1,
        }
        with pytest.raises(AssertionError, match="'id' must be a str"):
            check_story_completeness(story)

    @given(
        bad_title=st.one_of(
            st.integers(), st.none(), st.booleans(), st.lists(st.text())
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_string_title_fails(self, bad_title: Any):
        """A non-string ``title`` fails the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": bad_title,
            "description": "Desc",
            "acceptance_criteria": [],
            "story_points": 1,
        }
        with pytest.raises(AssertionError, match="'title' must be a str"):
            check_story_completeness(story)

    @given(
        bad_desc=st.one_of(st.integers(), st.none(), st.booleans(), st.lists(st.text()))
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_string_description_fails(self, bad_desc: Any):
        """A non-string ``description`` fails the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": "Title",
            "description": bad_desc,
            "acceptance_criteria": [],
            "story_points": 1,
        }
        with pytest.raises(AssertionError, match="'description' must be a str"):
            check_story_completeness(story)

    @given(
        bad_ac=st.one_of(
            st.text(min_size=0, max_size=10),
            st.integers(),
            st.none(),
            st.dictionaries(st.text(max_size=5), st.integers()),
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_list_acceptance_criteria_fails(self, bad_ac: Any):
        """A non-list ``acceptance_criteria`` fails the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": "Title",
            "description": "Desc",
            "acceptance_criteria": bad_ac,
            "story_points": 1,
        }
        with pytest.raises(
            AssertionError, match="'acceptance_criteria' must be a list"
        ):
            check_story_completeness(story)

    @given(sp=st.integers(max_value=0))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_non_positive_story_points_fails(self, sp: int):
        """Zero or negative ``story_points`` fails the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": "Title",
            "description": "Desc",
            "acceptance_criteria": [],
            "story_points": sp,
        }
        with pytest.raises(AssertionError, match="must be positive"):
            check_story_completeness(story)

    @given(
        bad_sp=st.one_of(
            st.floats(allow_nan=True, allow_infinity=True),
            st.text(min_size=1, max_size=10),
            st.none(),
            st.lists(st.integers(), max_size=2),
            st.booleans(),
        )
    )
    @settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
    def test_non_int_story_points_fails(self, bad_sp: Any):
        """A non-integer ``story_points`` fails the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": "Title",
            "description": "Desc",
            "acceptance_criteria": [],
            "story_points": bad_sp,
        }
        with pytest.raises(AssertionError, match="'story_points' must be an int"):
            check_story_completeness(story)

    def test_minimal_valid_story_passes(self):
        """Boundary: a minimal valid story with empty acceptance_criteria.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": "T",
            "description": "D",
            "acceptance_criteria": [],
            "story_points": 1,
        }
        check_story_completeness(story)

    def test_story_with_extra_fields_passes(self):
        """Extra fields beyond the required ones do not break the check.

        **Validates: Requirements 13.4**
        """
        story = {
            "id": "s1",
            "title": "Title",
            "description": "Desc",
            "acceptance_criteria": ["AC1"],
            "story_points": 3,
            "priority": "high",
            "assignee": "dev1",
        }
        check_story_completeness(story)

    @given(stories=st.lists(valid_story_st(), min_size=1, max_size=10))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_all_stories_in_decompose_result_pass(self, stories: List[Dict[str, Any]]):
        """All stories in a full run_decompose result pass the completeness check.

        **Validates: Requirements 13.4**
        """
        result: Dict[str, Any] = {
            "stories": stories,
            "tasks": [],
            "dependency_graph": {},
            "total_story_points": sum(s["story_points"] for s in stories),
        }
        for story in result["stories"]:
            check_story_completeness(story)

    def test_empty_dict_story_fails(self):
        """An empty dict fails the completeness check.

        **Validates: Requirements 13.4**
        """
        with pytest.raises(AssertionError, match="must contain"):
            check_story_completeness({})
