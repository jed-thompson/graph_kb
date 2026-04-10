"""Property tests for BasePlanSubgraphState and per-phase progress dictionaries.

Validates that the single-source-of-truth constants and base state class
in plan_state.py satisfy their structural invariants.
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck, strategies as st

from graph_kb_api.flows.v3.state.plan_state import (
    BasePlanSubgraphState,
    ContextSubgraphState,
    ResearchSubgraphState,
    PlanningSubgraphState,
    OrchestrateSubgraphState,
    AssemblySubgraphState,
    PlanState,
    PHASE_PROGRESS,
    CONTEXT_PROGRESS,
    RESEARCH_PROGRESS,
    PLANNING_PROGRESS,
    ORCHESTRATE_PROGRESS,
    ASSEMBLY_PROGRESS,
    PlanPhase,
)

# All subgraph state classes that inherit from BasePlanSubgraphState
_SUBGRAPH_STATE_CLASSES = [
    ContextSubgraphState,
    ResearchSubgraphState,
    PlanningSubgraphState,
    OrchestrateSubgraphState,
    AssemblySubgraphState,
    PlanState,
]

# The 10 shared fields declared in BasePlanSubgraphState
_BASE_FIELD_NAMES = list(BasePlanSubgraphState.__annotations__.keys())


# ---------------------------------------------------------------------------
# Property 1: BasePlanSubgraphState field inheritance and reducer preservation
# ---------------------------------------------------------------------------


class TestBasePlanSubgraphStateInheritance:
    """Feature: plan-feature-refactoring, Property 1: BasePlanSubgraphState
    field inheritance and reducer preservation
    """

    @given(cls=st.sampled_from(_SUBGRAPH_STATE_CLASSES))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_subclass_contains_all_base_fields(self, cls: type):
        """Every subgraph state class must contain all 10 shared fields from
        BasePlanSubgraphState in its annotations.
        """
        child_annotations = cls.__annotations__
        for field_name in _BASE_FIELD_NAMES:
            assert field_name in child_annotations, (
                f"{cls.__name__} is missing shared field {field_name!r} "
                f"from BasePlanSubgraphState"
            )

    @given(
        cls=st.sampled_from(_SUBGRAPH_STATE_CLASSES),
        field_name=st.sampled_from(_BASE_FIELD_NAMES),
    )
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_reducer_annotations_preserved(self, cls: type, field_name: str):
        """The annotation for each shared field in the subclass must be the
        exact same object as in BasePlanSubgraphState.

        TypedDict inheritance copies annotation references, so the child's
        ``__annotations__[field]`` is the same ForwardRef object as the
        base's.  We compare raw ``__annotations__`` (not resolved hints)
        because ``from __future__ import annotations`` stores them as
        ForwardRef strings, and resolving them via ``get_type_hints`` can
        re-evaluate factory calls like ``_capped_list_add(50)`` producing
        non-identical closures.
        """
        base_annotation = BasePlanSubgraphState.__annotations__[field_name]
        child_annotation = cls.__annotations__.get(field_name)
        assert child_annotation is not None, (
            f"{cls.__name__} is missing annotation for shared field {field_name!r}"
        )
        assert child_annotation is base_annotation, (
            f"{cls.__name__}.{field_name} annotation is not the same object as "
            f"BasePlanSubgraphState.{field_name}:\n"
            f"  base:  {base_annotation!r}\n"
            f"  child: {child_annotation!r}"
        )

    def test_base_has_exactly_10_fields(self):
        """BasePlanSubgraphState must declare exactly 10 shared fields.
        """
        assert len(_BASE_FIELD_NAMES) == 10, (
            f"BasePlanSubgraphState has {len(_BASE_FIELD_NAMES)} fields, "
            f"expected 10. Fields: {_BASE_FIELD_NAMES}"
        )

    def test_all_subclasses_inherit_from_base(self):
        """Every subgraph state class must have BasePlanSubgraphState in its
        TypedDict inheritance chain (verified via __annotations__ containment
        since TypedDict does not support issubclass checks).
        """
        base_fields = set(BasePlanSubgraphState.__annotations__)
        for cls in _SUBGRAPH_STATE_CLASSES:
            child_fields = set(cls.__annotations__)
            missing = base_fields - child_fields
            assert not missing, (
                f"{cls.__name__} does not contain all BasePlanSubgraphState "
                f"fields. Missing: {missing}"
            )


# ---------------------------------------------------------------------------
# Property 10b: Per-phase progress dictionaries are monotonically increasing
# and complete
# ---------------------------------------------------------------------------


class TestPhaseProgressProperty:
    """Feature: plan-feature-refactoring, Property 10b: Per-phase progress
    dictionaries are monotonically increasing and complete
    """

    @given(phase_name=st.sampled_from(list(PHASE_PROGRESS.keys())))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_values_monotonically_non_decreasing(self, phase_name: str):
        """Float values in each progress dict are monotonically non-decreasing
        in insertion order.
        """
        progress = PHASE_PROGRESS[phase_name]
        values = list(progress.values())
        for i in range(1, len(values)):
            assert values[i] >= values[i - 1], (
                f"PHASE_PROGRESS[{phase_name!r}]: value at index {i} "
                f"({values[i]}) < value at index {i - 1} ({values[i - 1]}). "
                f"Steps: {list(progress.keys())}, Values: {values}"
            )

    @given(phase_name=st.sampled_from(list(PHASE_PROGRESS.keys())))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_first_value_is_zero(self, phase_name: str):
        """The first value in each progress dict must be 0.0.
        """
        progress = PHASE_PROGRESS[phase_name]
        values = list(progress.values())
        assert len(values) > 0, f"PHASE_PROGRESS[{phase_name!r}] is empty"
        assert values[0] == 0.0, (
            f"PHASE_PROGRESS[{phase_name!r}]: first value is {values[0]}, expected 0.0"
        )

    @given(phase_name=st.sampled_from(list(PHASE_PROGRESS.keys())))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_last_value_in_valid_range(self, phase_name: str):
        """The last value in each progress dict must be in [0.95, 1.0].
        """
        progress = PHASE_PROGRESS[phase_name]
        values = list(progress.values())
        assert len(values) > 0, f"PHASE_PROGRESS[{phase_name!r}] is empty"
        assert 0.95 <= values[-1] <= 1.0, (
            f"PHASE_PROGRESS[{phase_name!r}]: last value is {values[-1]}, "
            f"expected in [0.95, 1.0]"
        )

    @given(phase_name=st.sampled_from(list(PHASE_PROGRESS.keys())))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_no_negative_or_exceeding_values(self, phase_name: str):
        """No value in any progress dict should be negative or exceed 1.0.
        """
        progress = PHASE_PROGRESS[phase_name]
        for step, value in progress.items():
            assert 0.0 <= value <= 1.0, (
                f"PHASE_PROGRESS[{phase_name!r}][{step!r}] = {value} "
                f"is outside [0.0, 1.0]"
            )

    def test_phase_progress_covers_all_phases(self):
        """PHASE_PROGRESS must have an entry for every phase in PlanPhase.
        """
        for phase in PlanPhase:
            assert phase.value in PHASE_PROGRESS, (
                f"PlanPhase.{phase.name} ({phase.value!r}) is missing from PHASE_PROGRESS"
            )

    def test_individual_dicts_match_phase_progress(self):
        """The individual progress dicts must be the same objects referenced in PHASE_PROGRESS.
        """
        assert PHASE_PROGRESS["context"] is CONTEXT_PROGRESS
        assert PHASE_PROGRESS["research"] is RESEARCH_PROGRESS
        assert PHASE_PROGRESS["planning"] is PLANNING_PROGRESS
        assert PHASE_PROGRESS["orchestrate"] is ORCHESTRATE_PROGRESS
        assert PHASE_PROGRESS["assembly"] is ASSEMBLY_PROGRESS
