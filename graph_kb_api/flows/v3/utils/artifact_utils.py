"""Artifact serialization utilities.

Extracted from ``SubgraphAwareNode._serialize_artifacts`` to break the
circular import between ``plan_dispatcher.py`` and ``subgraph_aware_node.py``.
"""

from __future__ import annotations

from graph_kb_api.flows.v3.state.plan_state import ArtifactManifestEntry, ArtifactRef


def _infer_content_type(artifact_name: str) -> str:
    """Infer MIME content type from artifact file extension."""
    if artifact_name.endswith(".json"):
        return "application/json"
    elif artifact_name.endswith(".md"):
        return "text/markdown"
    elif artifact_name.endswith(".jsonl"):
        return "application/jsonl"
    return "text/plain"


def serialize_artifacts(
    artifacts: dict[str, ArtifactRef],
) -> list[ArtifactManifestEntry]:
    """Convert artifact dict to manifest entries for interrupt payloads.

    Strips the ``specs/{session_id}/`` prefix from each key so the
    frontend can pass the short key directly to
    ``GET /plan/sessions/{id}/artifacts/{key}``.

    Handles all artifact types (code, document, diagram) consistently
    via ``_infer_content_type``.

    Args:
        artifacts: Mapping of artifact names to ``ArtifactRef`` dicts.

    Returns:
        List of ``ArtifactManifestEntry`` dicts suitable for frontend consumption.
    """
    entries: list[ArtifactManifestEntry] = []
    for name, ref in artifacts.items():
        short_key = ref["key"]
        # Strip "specs/{session_id}/" prefix → e.g. "research/full_findings.json"
        if "/" in short_key:
            short_key = short_key.split("/", 2)[-1]
        entry: ArtifactManifestEntry = {
            "key": short_key,
            "summary": ref["summary"],
            "size_bytes": ref["size_bytes"],
            "created_at": ref["created_at"],
            "content_type": _infer_content_type(short_key),
        }
        entries.append(entry)
    return entries
