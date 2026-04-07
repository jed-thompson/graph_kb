"""
Multi-repository research models.

Dataclasses representing detected inter-repo relationships.
CrossRepoSynthesisResult lives in research_models (Pydantic) and is
re-exported here for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal

from graph_kb_api.flows.v3.models.research_models import CrossRepoSynthesisResult

__all__ = ["CrossRepoSynthesisResult", "DetectedRelationship", "RelationshipKind"]

RelationshipKind = Literal["dependency", "rest", "grpc"]


@dataclass
class DetectedRelationship:
    """A relationship candidate found by static analysis."""

    source: str
    target: str
    relationship_type: RelationshipKind
    evidence: List[str] = field(default_factory=list)
    confidence: float = 0.0
