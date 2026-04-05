"""Data models for code understanding and analysis results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .analysis_enums import (
    DomainCategory,
    EntryPointType,
    RelationType,
    StepType,
)
from .enums import SymbolKind


@dataclass
class EntryPoint:
    """Represents an entry point in the codebase."""

    id: str
    name: str
    file_path: str
    entry_type: EntryPointType
    symbol_kind: SymbolKind
    line_number: Optional[int] = None
    http_method: Optional[str] = None
    route: Optional[str] = None
    description: Optional[str] = None


@dataclass
class DataFlowStep:
    """A single step in a data flow trace."""

    symbol_id: str
    symbol_name: str
    file_path: str
    step_type: StepType
    depth: int
    docstring: Optional[str] = None


@dataclass
class DataFlow:
    """A complete data flow trace from an entry point."""

    entry_point: EntryPoint
    steps: List[DataFlowStep]
    is_truncated: bool
    max_depth_reached: int


@dataclass
class DomainRelationship:
    """A relationship between domain concepts."""

    target_concept_id: str
    target_concept_name: str
    relationship_type: RelationType


@dataclass
class DomainConcept:
    """A business domain concept identified in the codebase."""

    id: str
    name: str
    category: DomainCategory
    file_path: str
    description: Optional[str] = None
    relationships: List[DomainRelationship] = field(default_factory=list)


@dataclass
class NarrativeSummary:
    """A human-readable narrative summary of a codebase."""

    repo_id: str
    purpose: str
    capabilities: List[str]
    components: List[str]
    how_it_works: str
    full_narrative: str


@dataclass
class CodeAnalysisResult:
    """Complete analysis result for a repository."""

    repo_id: str
    entry_points: List[EntryPoint]
    domain_concepts: List[DomainConcept]
    generated_at: datetime
    narrative: Optional[NarrativeSummary] = None
