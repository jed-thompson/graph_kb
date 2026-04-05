"""
Decomposition models for feature breakdown.

These dataclasses represent user stories, tasks, and acceptance criteria
used by the DecomposeAgent during Phase 4 of the feature spec wizard.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AcceptanceCriterion:
    """Represents an acceptance criterion for a story."""

    id: str
    description: str
    type: str  # functional, non_functional, edge_case
    verification: str  # how to verify this is met


@dataclass
class UserStory:
    """Represents a user story with all details."""

    id: str
    title: str
    description: str  # As a <role>, I want <feature>, so that <benefit>
    acceptance_criteria: List[AcceptanceCriterion]
    story_points: int  # 1, 2, 3, 5, 8, 13, 21
    priority: str  # must_have, should_have, nice_to_have
    phase_id: str  # Maps to RoadmapPhase.id
    dependencies: List[str]  # Story IDs this depends on
    technical_notes: str
    risks: List[str]
    labels: List[str] = field(default_factory=list)
    status: str = "draft"  # draft, ready, in_progress, blocked, done


@dataclass
class Task:
    """Represents a technical task within a story."""

    id: str
    story_id: str
    title: str
    description: str
    estimated_hours: float
    assignee_type: str  # backend, frontend, devops, qa, documentation
    dependencies: List[str]  # Task IDs this depends on
    status: str = "todo"  # todo, in_progress, blocked, done


@dataclass
class StoryMap:
    """Complete story map with all decomposition details."""

    stories: List[UserStory]
    tasks: List[Task]
    total_story_points: int
    dependency_graph: Dict[str, List[str]]
    phase_mapping: Dict[str, List[str]]  # phase_id -> story_ids
    summary: str
