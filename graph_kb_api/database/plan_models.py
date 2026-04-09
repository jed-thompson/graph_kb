"""SQLAlchemy ORM model for Plan session persistence.

Stores plan session metadata for browser-close resume and
cross-server-restart session recovery. LangGraph checkpoints
hold the full workflow state; this table holds the lightweight
index needed to list and reconnect sessions.
"""

from datetime import datetime

from sqlalchemy import (
    JSON as JSONB,
)
from sqlalchemy import (
    DateTime,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from graph_kb_api.database.base import Base


class PlanSession(Base):
    """Persistent record for a /plan workflow session.

    Columns mirror the subset of PlanState needed to reconstruct
    the UI stepper bar on reconnect without loading the full
    LangGraph checkpoint.
    """

    __tablename__ = "plan_sessions"
    __table_args__ = (
        Index("ix_plan_sessions_user_id", "user_id"),
    )

    # Primary key — same UUID used as LangGraph thread_id prefix
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # LangGraph thread_id (format: "plan-{session_id}")
    thread_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Ownership
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Human-readable metadata
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Workflow state snapshot (JSONB for flexibility)
    workflow_status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="idle",
    )
    current_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completed_phases: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fingerprints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    budget_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_items: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Orchestrate task_results persisted after each task so they survive restarts.
    # The orchestrate subgraph uses use_default_checkpointer=False, so the parent
    # LangGraph checkpoint does not hold subgraph-internal state between tasks.
    task_results: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Assembly completion evidence persisted by AssembleNode so that if the server
    # dies before the parent LangGraph checkpoint is written, reconnect recovery can
    # still detect that assembly finished and re-emit plan.complete.
    spec_document_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
