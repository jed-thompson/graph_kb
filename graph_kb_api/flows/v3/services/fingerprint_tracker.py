"""FingerprintTracker static utility class for selective recompilation.

Tracks content hashes per phase and determines which downstream phases
need re-running via the CASCADE_MAP.  All methods are @staticmethod
with no instance state.

Import-time validation ensures CASCADE_MAP is acyclic.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Dict, List

from graph_kb_api.flows.v3.state.plan_state import (
    CASCADE_MAP,
    ArtifactRef,
    PhaseFingerprint,
    PlanPhase,
)


class CascadeConfigError(Exception):
    """Raised if CASCADE_MAP contains a cycle."""

    pass


def _validate_cascade_map_acyclic(cascade_map: Dict[PlanPhase, List[PlanPhase]]) -> None:
    """Raise ``CascadeConfigError`` if *cascade_map* has a cycle.

    Uses DFS-based cycle detection over all phases.
    """
    visited: set[PlanPhase] = set()
    in_stack: set[PlanPhase] = set()

    def dfs(node: PlanPhase) -> None:
        if node in in_stack:
            raise CascadeConfigError(f"Cycle detected in CASCADE_MAP at phase: {node}")
        if node in visited:
            return
        visited.add(node)
        in_stack.add(node)
        for downstream in cascade_map.get(node, []):
            dfs(downstream)
        in_stack.discard(node)

    for phase in cascade_map:
        dfs(phase)


# Validate at import time
_validate_cascade_map_acyclic(CASCADE_MAP)


class FingerprintTracker:
    """Computes content hashes per phase for selective recompilation.

    Uses static methods only — no instance state.
    """

    @staticmethod
    def compute_fingerprint(phase: str, input_refs: List[ArtifactRef]) -> str:
        """Return a 64-char SHA-256 hex string for *phase* and *input_refs*.

        Sorts the ``content_hash`` values from *input_refs* lexicographically,
        concatenates them with the phase name, and hashes the result.
        """
        sorted_hashes = sorted(ref["content_hash"] for ref in input_refs)
        combined = phase + ":" + ",".join(sorted_hashes)
        return hashlib.sha256(combined.encode()).hexdigest()

    @staticmethod
    def get_dirty_phases(
        fingerprints: Dict[str, PhaseFingerprint],
        changed_phase: str,
        cascade_map: Dict[PlanPhase, List[PlanPhase]],
    ) -> List[str]:
        """Return downstream phases that have existing fingerprints.

        Looks up *cascade_map[changed_phase]* and returns only those
        downstream phases that already appear in *fingerprints*.
        """
        downstream: list[PlanPhase] = cascade_map.get(PlanPhase(changed_phase), [])
        return [p for p in downstream if p in fingerprints]

    @staticmethod
    def update_fingerprint(
        fingerprints: Dict[str, PhaseFingerprint],
        phase: str,
        new_hash: str,
        output_refs: List[str],
    ) -> Dict[str, PhaseFingerprint]:
        """Return a new fingerprints dict without mutating the input.

        Creates a shallow copy and sets the entry for *phase* to a fresh
        ``PhaseFingerprint`` with the current timestamp.
        """
        new_fp = dict(fingerprints)
        new_fp[phase] = PhaseFingerprint(
            phase=phase,
            input_hash=new_hash,
            output_refs=output_refs,
            completed_at=datetime.now(UTC).isoformat(),
        )
        return new_fp

    @staticmethod
    def compute_phase_data_fingerprint(phase: str, data: Dict[str, Any]) -> str:
        """Return a 64-char SHA-256 hex string for *phase* output *data*.

        Serializes the dict to deterministic JSON (sorted keys) concatenated
        with the phase name, then hashes.  Used by approval nodes to record
        a snapshot of the phase output for later dirty-detection on
        backward navigation.
        """
        # Only include serializable, hash-relevant keys (skip large blobs).
        # Exclude keys that typically contain large inline arrays from research.
        _SKIP_KEYS = {"web_results", "vector_results", "graph_results", "context_cards", "knowledge_gaps"}
        serializable = {
            k: v
            for k, v in data.items()
            if isinstance(v, (str, int, float, bool, list, dict, type(None))) and k not in _SKIP_KEYS
        }
        canonical = json.dumps(serializable, sort_keys=True, default=str)
        combined = phase + ":" + canonical
        return hashlib.sha256(combined.encode()).hexdigest()
