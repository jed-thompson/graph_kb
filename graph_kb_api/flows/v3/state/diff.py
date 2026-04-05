from __future__ import annotations

"""
Diff state schema for differential update workflow.

This module defines the state structure for the differential update workflow,
which handles fetching repository updates, computing diffs, analyzing impact,
and applying selective updates with rollback capability.
"""

import operator
from typing import Annotated, List, Optional

from typing_extensions import TypedDict

from graph_kb_api.flows.v3.state.common import BaseCommandState


class DiffState(BaseCommandState, TypedDict):
    """
    State for differential update workflow.

    This state extends BaseCommandState with fields specific to differential
    repository updates including repository validation, diff computation,
    impact analysis, user selection, rollback management, and verification.
    """

    # Input - Repository information (Requirement 3.1)
    repo_url: str

    # Repository validation (Requirement 3.1)
    repo_indexed: bool

    # Diff computation (Requirement 3.1)
    has_changes: bool
    changed_files: List[str]
    deleted_files: List[str]

    # Impact analysis (Requirements 3.2, 3.3)
    # Use operator.add reducer to accumulate existing symbols across nodes
    existing_symbols: Annotated[List[dict], operator.add]
    predicted_changes: Optional[dict]
    impact_summary: Optional[str]

    # User selection (Requirement 3.4)
    selected_files: Optional[List[str]]
    user_approved_update: Optional[bool]

    # Rollback (Requirement 3.5)
    rollback_checkpoint_id: Optional[str]

    # Verification (Requirements 3.6, 3.7)
    verification_passed: bool
    verification_details: Optional[dict]
    rollback_offered: bool
    user_rollback_decision: Optional[bool]
