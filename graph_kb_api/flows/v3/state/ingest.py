"""
Ingest state schema for repository ingestion workflow.

This module defines the state structure for the repository ingestion workflow,
which handles cloning, analyzing, indexing, and validating code repositories.
"""

import operator
from typing import Annotated, List, Literal, Optional

from typing_extensions import TypedDict

from graph_kb_api.flows.v3.state.common import BaseCommandState


class IngestState(BaseCommandState, TypedDict):
    """
    State for repository ingestion workflow.

    This state extends BaseCommandState with fields specific to repository
    ingestion including repository information, preview data, configuration,
    indexing progress, error handling, and validation results.
    """

    # Input - Repository information
    repo_url_or_id: str  # Can be either GitHub URL or repo_id
    repo_url: str  # Resolved GitHub URL
    branch: str
    resume_flag: bool

    # Resolution tracking
    resolved_from_repo_id: Optional[bool]
    original_repo_id: Optional[str]

    # Repository info
    repo_path: Optional[str]
    repo_exists: bool

    # Preview (Requirement 2.1)
    preview_data: Optional[dict]  # Contains: file_count, languages, estimated_time
    user_approved_preview: Optional[bool]

    # Configuration (Requirement 2.2)
    exclusion_patterns: List[str]
    embedding_config: Optional[dict]

    # Indexing progress (Requirement 2.3)
    indexing_phase: str
    files_processed: int
    total_files: int
    symbols_extracted: int
    chunks_created: int
    embeddings_generated: int

    # Error handling (Requirement 2.4)
    # Use operator.add reducer to accumulate failed files across nodes
    failed_files: Annotated[List[dict], operator.add]
    user_error_decision: Optional[Literal["retry", "skip", "abort"]]

    # Validation (Requirement 2.5)
    post_index_stats: Optional[dict]
