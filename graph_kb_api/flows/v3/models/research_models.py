"""
Domain models for the research workflow.

Shared between the WebSocket layer (research_events) and flow agents.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ResearchContextCard(BaseModel):
    """A single context card with mermaid-enabled content."""

    id: str
    source_type: str = Field(..., description="web, document, repository, generated")
    source_url: Optional[str] = None
    source_name: str
    title: str
    content: str = Field(..., description="Markdown content with possible mermaid diagrams")
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    created_at: str


class ResearchGap(BaseModel):
    """A detected knowledge gap requiring user input."""

    id: str
    category: str = Field(..., description="scope, technical, constraint, stakeholder")
    question: str
    context: str
    suggested_answers: List[str] = Field(default_factory=list)
    impact: str = Field(..., description="high, medium, low")


class ResearchRisk(BaseModel):
    """A detected risk in the research."""

    id: str
    category: str = Field(..., description="technical, timeline, resource, dependency")
    description: str
    severity: str = Field(..., description="critical, high, medium, low")
    mitigation: str


class ResearchFindings(BaseModel):
    """Aggregated research findings."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    summary: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    key_insights: List[str] = Field(default_factory=list)
    related_modules: List[Dict[str, str]] = Field(default_factory=list)
    risks: List[ResearchRisk] = Field(default_factory=list)


class ResearchReviewResult(BaseModel):
    """Result of LLM review of gathered context."""

    id: str
    summary: str
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    overall_assessment: str = Field(
        ...,
        description="excellent, good, adequate, needs_improvement",
    )
    reviewed_at: str


class CrossRepoSynthesisResult(BaseModel):
    """Result of the cross-repo synthesis pass."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    summary: str
    api_contract_gaps: List[Dict] = Field(default_factory=list)
    cross_cutting_risks: List[Dict] = Field(default_factory=list)
    dependency_issues: List[Dict] = Field(default_factory=list)

    def to_dict(self) -> Dict:
        return self.model_dump(by_alias=True)
