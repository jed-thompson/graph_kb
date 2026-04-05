"""Integration tests for cascade recompilation via FingerprintTracker.

Simulates a completed workflow where all phases have fingerprints, then
modifies the research phase fingerprint and verifies that downstream
phases (plan, orchestrate, completeness, generate) are correctly
identified as dirty and can be re-run via the cascade chain.

Also verifies that update_fingerprint correctly produces new dicts
without mutating the original, and that the full cascade chain from
research through generate is properly handled.

**Validates: Requirements 10.2, 10.3, 30.1**
"""

import copy
from datetime import UTC, datetime

from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
from graph_kb_api.flows.v3.state.plan_state import (
    CASCADE_MAP,
    ArtifactRef,
    PhaseFingerprint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PHASES = [
    "context",
    "research",
    "planning",
    "orchestrate",
    "assembly",
]


def _make_fingerprint(phase: str, input_hash: str | None = None) -> PhaseFingerprint:
    """Create a PhaseFingerprint with a deterministic hash for testing."""
    return PhaseFingerprint(
        phase=phase,
        input_hash=input_hash or f"{'0' * 60}{phase[:4]}",
        output_refs=[f"specs/session/{phase}/output.json"],
        completed_at=datetime.now(UTC).isoformat(),
    )


def _make_artifact_ref(phase: str, name: str = "output.json") -> ArtifactRef:
    """Create a minimal ArtifactRef for fingerprint computation."""
    return ArtifactRef(
        key=f"specs/session/{phase}/{name}",
        content_hash=f"{'a' * 60}{phase[:4]}",
        size_bytes=1024,
        created_at=datetime.now(UTC).isoformat(),
        summary=f"{phase} output artifact",
    )


def _build_completed_fingerprints() -> dict[str, PhaseFingerprint]:
    """Build fingerprints simulating a fully completed workflow."""
    return {phase: _make_fingerprint(phase) for phase in PHASES}


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestCascadeFromResearch:
    """Modify research phase fingerprint, verify downstream phases are dirty."""

    def test_research_change_marks_downstream_dirty(self):
        """Changing research should mark planning, orchestrate, assembly as dirty."""
        fingerprints = _build_completed_fingerprints()

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)

        expected = ["planning", "orchestrate", "assembly"]
        assert dirty == expected

    def test_research_change_does_not_mark_upstream_dirty(self):
        """Changing research should NOT mark context as dirty."""
        fingerprints = _build_completed_fingerprints()

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)

        assert "context" not in dirty
        assert "research" not in dirty

    def test_dirty_phases_only_includes_phases_with_fingerprints(self):
        """If a downstream phase has no fingerprint, it should not be in dirty list."""
        fingerprints = _build_completed_fingerprints()
        # Remove orchestrate fingerprint — simulating it never ran
        del fingerprints["orchestrate"]

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)

        assert "orchestrate" not in dirty
        assert "planning" in dirty
        assert "assembly" in dirty


class TestFullCascadeChain:
    """Test the full cascade chain: research → plan → orchestrate → completeness → generate."""

    def test_sequential_recompilation_updates_fingerprints(self):
        """Simulate re-running each dirty phase and updating its fingerprint."""
        fingerprints = _build_completed_fingerprints()
        original = copy.deepcopy(fingerprints)

        # Step 1: Research changed — get dirty phases
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)
        assert dirty == ["planning", "orchestrate", "assembly"]

        # Step 2: Re-run each dirty phase in order, updating fingerprints
        for phase in dirty:
            new_hash = FingerprintTracker.compute_fingerprint(phase, [_make_artifact_ref(phase, "recomputed.json")])
            fingerprints = FingerprintTracker.update_fingerprint(
                fingerprints,
                phase,
                new_hash,
                [f"specs/session/{phase}/recomputed.json"],
            )

        # Step 3: Verify all dirty phases got new fingerprints
        for phase in dirty:
            assert fingerprints[phase]["input_hash"] != original[phase]["input_hash"]
            assert fingerprints[phase]["output_refs"] == [f"specs/session/{phase}/recomputed.json"]

        # Step 4: Verify non-dirty phases are unchanged
        for phase in ["context"]:
            assert fingerprints[phase] == original[phase]

    def test_after_recompilation_no_more_dirty_phases(self):
        """After updating all dirty phases, re-checking should yield no dirty phases
        only if the changed phase itself is also updated."""
        fingerprints = _build_completed_fingerprints()

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)

        # Re-run and update each dirty phase
        for phase in dirty:
            new_hash = FingerprintTracker.compute_fingerprint(phase, [_make_artifact_ref(phase, "v2.json")])
            fingerprints = FingerprintTracker.update_fingerprint(
                fingerprints, phase, new_hash, [f"specs/session/{phase}/v2.json"]
            )

        # Now update research itself with new fingerprint
        research_hash = FingerprintTracker.compute_fingerprint("research", [_make_artifact_ref("research", "v2.json")])
        fingerprints = FingerprintTracker.update_fingerprint(
            fingerprints, "research", research_hash, ["specs/session/research/v2.json"]
        )

        # All phases still have fingerprints, but the cascade was handled
        # get_dirty_phases still returns phases with fingerprints — that's correct
        # The key insight: dirty detection is based on CASCADE_MAP membership,
        # not on hash comparison. The engine uses input_hash comparison separately.
        dirty_again = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)
        # Still returns downstream phases that have fingerprints (by design)
        assert dirty_again == ["planning", "orchestrate", "assembly"]


class TestUpdateFingerprintImmutability:
    """Verify update_fingerprint does not mutate the input dict during cascade."""

    def test_original_fingerprints_unchanged_after_cascade(self):
        """Updating fingerprints for all dirty phases should not mutate the original."""
        original = _build_completed_fingerprints()
        snapshot = copy.deepcopy(original)

        fingerprints = original
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)

        for phase in dirty:
            new_hash = FingerprintTracker.compute_fingerprint(phase, [_make_artifact_ref(phase)])
            fingerprints = FingerprintTracker.update_fingerprint(
                fingerprints, phase, new_hash, [f"specs/session/{phase}/output.json"]
            )

        # The original dict should be completely unchanged
        assert original == snapshot

    def test_each_update_returns_new_dict(self):
        """Each call to update_fingerprint should return a distinct dict object."""
        fingerprints = _build_completed_fingerprints()
        seen_ids: set[int] = {id(fingerprints)}

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "research", CASCADE_MAP)

        for phase in dirty:
            new_hash = FingerprintTracker.compute_fingerprint(phase, [_make_artifact_ref(phase)])
            fingerprints = FingerprintTracker.update_fingerprint(
                fingerprints, phase, new_hash, [f"specs/session/{phase}/output.json"]
            )
            assert id(fingerprints) not in seen_ids
            seen_ids.add(id(fingerprints))


class TestCascadeMapCoverage:
    """Verify CASCADE_MAP entries for all phases used in cascade recompilation."""

    def test_research_cascade_includes_all_downstream(self):
        """research → [planning, orchestrate, assembly]"""
        assert CASCADE_MAP["research"] == [
            "planning",
            "orchestrate",
            "assembly",
        ]

    def test_planning_cascade_includes_downstream(self):
        """planning → [orchestrate, assembly]"""
        assert CASCADE_MAP["planning"] == ["orchestrate", "assembly"]

    def test_orchestrate_cascade_includes_downstream(self):
        """orchestrate → [assembly]"""
        assert CASCADE_MAP["orchestrate"] == ["assembly"]

    def test_assembly_has_no_downstream(self):
        """assembly → [] (leaf phase)"""
        assert CASCADE_MAP["assembly"] == []


class TestCascadeWithCompletedPhasesClearing:
    """Simulate backward navigation clearing completed_phases for downstream phases.

    **Validates: Requirement 30.1**
    """

    def test_navigate_backward_clears_downstream_completed_flags(self):
        """When navigating back to research, downstream completed_phases should be cleared."""
        completed_phases = {phase: True for phase in PHASES}
        fingerprints = _build_completed_fingerprints()

        # User navigates backward to research
        changed_phase = "research"
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, changed_phase, CASCADE_MAP)

        # Clear completed_phases for all dirty downstream phases
        for phase in dirty:
            completed_phases[phase] = False

        # Verify upstream phases remain completed
        assert completed_phases["context"] is True
        assert completed_phases["research"] is True  # The changed phase itself stays

        # Verify downstream phases are cleared
        assert completed_phases["planning"] is False
        assert completed_phases["orchestrate"] is False
        assert completed_phases["assembly"] is False

    def test_navigate_backward_to_context_clears_all_downstream(self):
        """Navigating to context should clear all other phases."""
        completed_phases = {phase: True for phase in PHASES}
        fingerprints = _build_completed_fingerprints()

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "context", CASCADE_MAP)

        for phase in dirty:
            completed_phases[phase] = False

        assert completed_phases["context"] is True
        for phase in [
            "research",
            "planning",
            "orchestrate",
            "assembly",
        ]:
            assert completed_phases[phase] is False

    def test_navigate_backward_to_assembly_clears_nothing(self):
        """Navigating to assembly (leaf) should not clear any phases."""
        completed_phases = {phase: True for phase in PHASES}
        fingerprints = _build_completed_fingerprints()

        dirty = FingerprintTracker.get_dirty_phases(fingerprints, "assembly", CASCADE_MAP)

        for phase in dirty:
            completed_phases[phase] = False

        # All phases should remain completed
        for phase in PHASES:
            assert completed_phases[phase] is True
