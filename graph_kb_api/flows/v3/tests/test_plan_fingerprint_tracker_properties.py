"""Property-based tests for FingerprintTracker.

Properties 10-12 validate fingerprint order independence, dirty phase
detection correctness, and fingerprint update immutability across
randomly generated inputs.
"""

import copy
import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.services.fingerprint_tracker import FingerprintTracker
from graph_kb_api.flows.v3.state.plan_state import (
    CASCADE_MAP,
    ArtifactRef,
    PhaseFingerprint,
)

VALID_PHASES = [
    "context",
    "research",
    "planning",
    "orchestrate",
    "assembly",
]

hex64_st = st.from_regex(r"[0-9a-f]{64}", fullmatch=True)
phase_st = st.sampled_from(VALID_PHASES)


@st.composite
def artifact_ref(draw: st.DrawFn) -> ArtifactRef:
    return ArtifactRef(
        key=draw(st.text(min_size=1, max_size=60)),
        content_hash=draw(hex64_st),
        size_bytes=draw(st.integers(min_value=0, max_value=10_000_000)),
        created_at="2024-01-01T00:00:00Z",
        summary=draw(st.text(min_size=1, max_size=100)),
    )


@st.composite
def artifact_ref_list(draw: st.DrawFn) -> list[ArtifactRef]:
    return draw(st.lists(artifact_ref(), min_size=1, max_size=10))


@st.composite
def phase_fingerprint(draw: st.DrawFn, phase=None) -> PhaseFingerprint:
    return PhaseFingerprint(
        phase=phase or draw(phase_st),
        input_hash=draw(hex64_st),
        output_refs=draw(st.lists(st.text(min_size=1, max_size=40), max_size=5)),
        completed_at="2024-01-01T00:00:00Z",
    )


@st.composite
def fingerprints_dict(draw: st.DrawFn) -> dict[str, PhaseFingerprint]:
    phases = draw(st.lists(phase_st, max_size=len(VALID_PHASES), unique=True))
    result: dict[str, PhaseFingerprint] = {}
    for p in phases:
        result[p] = draw(phase_fingerprint(phase=p))
    return result


class TestFingerprintOrderIndependence:
    """Property 10: Fingerprint Order Independence

    For any phase and list of ArtifactRefs, compute_fingerprint should
    return the same hash regardless of the order of input_refs.
    The result should always be a 64-char hex string.

    **Validates: Requirements 9.1, 9.2, 9.3**
    """

    @given(phase=phase_st, refs=artifact_ref_list())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_same_hash_regardless_of_order(self, phase, refs):
        h1 = FingerprintTracker.compute_fingerprint(phase, refs)
        h2 = FingerprintTracker.compute_fingerprint(phase, list(reversed(refs)))
        assert h1 == h2

    @given(phase=phase_st, refs=artifact_ref_list())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_result_is_64_char_hex(self, phase, refs):
        result = FingerprintTracker.compute_fingerprint(phase, refs)
        assert len(result) == 64
        assert re.fullmatch(r"[0-9a-f]{64}", result)

    @given(
        phase=phase_st,
        refs=st.lists(artifact_ref(), min_size=2, max_size=10),
        data=st.data(),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_shuffled_order_same_hash(self, phase, refs, data):
        shuffled = data.draw(st.permutations(refs))
        h1 = FingerprintTracker.compute_fingerprint(phase, refs)
        h2 = FingerprintTracker.compute_fingerprint(phase, shuffled)
        assert h1 == h2


class TestDirtyPhaseDetectionCorrectness:
    """Property 11: Dirty Phase Detection Correctness

    get_dirty_phases should return only downstream phases that have
    existing fingerprints. Phases not in the cascade_map for the
    changed_phase should never be returned. Phases without existing
    fingerprints should never be returned.

    **Validates: Requirement 10.2**
    """

    @given(fingerprints=fingerprints_dict(), changed=phase_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_only_downstream_phases_returned(self, fingerprints, changed):
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, changed, CASCADE_MAP)
        downstream = set(CASCADE_MAP.get(changed, []))
        for phase in dirty:
            assert phase in downstream

    @given(fingerprints=fingerprints_dict(), changed=phase_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_only_phases_with_fingerprints_returned(self, fingerprints, changed):
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, changed, CASCADE_MAP)
        for phase in dirty:
            assert phase in fingerprints

    @given(fingerprints=fingerprints_dict(), changed=phase_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_non_downstream_phases_never_returned(self, fingerprints, changed):
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, changed, CASCADE_MAP)
        downstream = set(CASCADE_MAP.get(changed, []))
        non_downstream = set(VALID_PHASES) - downstream
        for phase in dirty:
            assert phase not in non_downstream

    @given(fingerprints=fingerprints_dict(), changed=phase_st)
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_result_is_complete(self, fingerprints, changed):
        dirty = FingerprintTracker.get_dirty_phases(fingerprints, changed, CASCADE_MAP)
        downstream = CASCADE_MAP.get(changed, [])
        expected = [p for p in downstream if p in fingerprints]
        assert dirty == expected


class TestFingerprintUpdateImmutability:
    """Property 12: Fingerprint Update Immutability

    update_fingerprint should return a new dict without mutating the
    input. The original fingerprints dict should be unchanged after
    the call. The returned dict should contain the updated phase entry.

    **Validates: Requirement 11.3**
    """

    @given(
        fingerprints=fingerprints_dict(),
        phase=phase_st,
        new_hash=hex64_st,
        output_refs=st.lists(st.text(min_size=1, max_size=40), max_size=5),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_original_not_mutated(self, fingerprints, phase, new_hash, output_refs):
        snapshot = copy.deepcopy(fingerprints)
        FingerprintTracker.update_fingerprint(fingerprints, phase, new_hash, output_refs)
        assert fingerprints == snapshot

    @given(
        fingerprints=fingerprints_dict(),
        phase=phase_st,
        new_hash=hex64_st,
        output_refs=st.lists(st.text(min_size=1, max_size=40), max_size=5),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_returns_new_dict(self, fingerprints, phase, new_hash, output_refs):
        result = FingerprintTracker.update_fingerprint(fingerprints, phase, new_hash, output_refs)
        assert result is not fingerprints

    @given(
        fingerprints=fingerprints_dict(),
        phase=phase_st,
        new_hash=hex64_st,
        output_refs=st.lists(st.text(min_size=1, max_size=40), max_size=5),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_updated_phase_present(self, fingerprints, phase, new_hash, output_refs):
        result = FingerprintTracker.update_fingerprint(fingerprints, phase, new_hash, output_refs)
        assert phase in result
        assert result[phase]["phase"] == phase
        assert result[phase]["input_hash"] == new_hash
        assert result[phase]["output_refs"] == output_refs
        assert len(result[phase]["completed_at"]) > 0

    @given(
        fingerprints=fingerprints_dict(),
        phase=phase_st,
        new_hash=hex64_st,
        output_refs=st.lists(st.text(min_size=1, max_size=40), max_size=5),
    )
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_other_phases_preserved(self, fingerprints, phase, new_hash, output_refs):
        result = FingerprintTracker.update_fingerprint(fingerprints, phase, new_hash, output_refs)
        for p, fp in fingerprints.items():
            if p != phase:
                assert p in result
                assert result[p] == fp
