"""consolidated schema

Revision ID: 0001
Revises:
Create Date: 2026-04-02 00:00:00.000000

Baseline schema covering all active tables. Spec wizard tables were removed
as they are unused.

Tables:
  repositories, documents, file_index, pending_chunks,
  failed_embedding_chunks, embedding_progress, indexing_progress,
  user_preferences, plan_sessions, document_store, document_links
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers — raw SQL so every index op is safe to re-run
# ---------------------------------------------------------------------------

def _idx(name: str, table: str, cols: list) -> None:
    col_list = ", ".join(cols)
    op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col_list})")


def _uidx(name: str, table: str, cols: list, where: str = "") -> None:
    col_list = ", ".join(cols)
    where_clause = f" WHERE {where}" if where else ""
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({col_list}){where_clause}"
    )


def upgrade() -> None:
    # =========================================================================
    # repositories
    # =========================================================================
    op.create_table(
        "repositories",
        sa.Column("repo_id", sa.String(255), primary_key=True),
        sa.Column("git_url", sa.String(500), nullable=False),
        sa.Column("default_branch", sa.String(100), nullable=False),
        sa.Column("local_path", sa.String(500), nullable=False),
        sa.Column("last_indexed_commit", sa.String(40), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("indexing_phase", sa.String(50), nullable=True, server_default="indexing"),
        if_not_exists=True,
    )

    # =========================================================================
    # documents
    # =========================================================================
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.String(255), primary_key=True),
        sa.Column("original_name", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("parent_name", sa.String(255), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("collection_name", sa.String(255), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("s3_key", sa.String(500), nullable=True),
        sa.Column("s3_bucket", sa.String(255), nullable=True),
        sa.Column("file_size", sa.Integer, nullable=True),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )

    # =========================================================================
    # user_preferences
    # =========================================================================
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("settings_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )

    # =========================================================================
    # file_index  (child of repositories, CASCADE)
    # =========================================================================
    op.create_table(
        "file_index",
        sa.Column(
            "repo_id",
            sa.String(255),
            sa.ForeignKey("repositories.repo_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("file_path", sa.String(1000), primary_key=True, nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("symbol_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        if_not_exists=True,
    )

    # =========================================================================
    # pending_chunks  (child of repositories, CASCADE)
    # =========================================================================
    op.create_table(
        "pending_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.String(255),
            sa.ForeignKey("repositories.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=True),
        sa.Column("end_line", sa.Integer, nullable=True),
        sa.Column("chunk_type", sa.String(50), nullable=True),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column("symbol_ids_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        comment="Stores chunks between indexing and embedding phases",
        if_not_exists=True,
    )
    _idx("ix_pending_chunks_repo_id", "pending_chunks", ["repo_id"])
    _uidx("uq_pending_chunks_repo_chunk", "pending_chunks", ["repo_id", "chunk_id"])

    # =========================================================================
    # failed_embedding_chunks  (child of repositories, CASCADE)
    # =========================================================================
    op.create_table(
        "failed_embedding_chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "repo_id",
            sa.String(255),
            sa.ForeignKey("repositories.repo_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("start_line", sa.Integer, nullable=True),
        sa.Column("end_line", sa.Integer, nullable=True),
        sa.Column("chunk_type", sa.String(50), nullable=True),
        sa.Column("language", sa.String(50), nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column("symbol_ids_json", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(timezone=True), nullable=True),
        comment="Stores chunks that failed during embedding for retry",
        if_not_exists=True,
    )
    _idx("ix_failed_embedding_chunks_repo_id", "failed_embedding_chunks", ["repo_id"])
    _uidx("uq_failed_chunks_repo_chunk", "failed_embedding_chunks", ["repo_id", "chunk_id"])

    # =========================================================================
    # embedding_progress  (child of repositories, CASCADE)
    # =========================================================================
    op.create_table(
        "embedding_progress",
        sa.Column(
            "repo_id",
            sa.String(255),
            sa.ForeignKey("repositories.repo_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("total_chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedded_chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("current_chunk_idx", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        if_not_exists=True,
    )

    # =========================================================================
    # indexing_progress  (child of repositories, CASCADE)
    # =========================================================================
    op.create_table(
        "indexing_progress",
        sa.Column(
            "repo_id",
            sa.String(255),
            sa.ForeignKey("repositories.repo_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("phase", sa.String(50), nullable=False),
        sa.Column("total_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_files", sa.Integer, nullable=False, server_default="0"),
        sa.Column("current_file", sa.String(1000), nullable=True),
        sa.Column("total_chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_symbols", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_relationships", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedded_chunks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_chunks_to_embed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        if_not_exists=True,
    )

    # =========================================================================
    # plan_sessions
    # =========================================================================
    op.create_table(
        "plan_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("thread_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("workflow_status", sa.String(50), nullable=False, server_default="idle"),
        sa.Column("current_phase", sa.String(50), nullable=True),
        sa.Column("completed_phases", sa.JSON, nullable=True),
        sa.Column("fingerprints", sa.JSON, nullable=True),
        sa.Column("budget_state", sa.JSON, nullable=True),
        sa.Column("context_items", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        comment="Persistent record for a /plan workflow session",
        if_not_exists=True,
    )
    _idx("ix_plan_sessions_user_id", "plan_sessions", ["user_id"])

    # =========================================================================
    # document_store  (generic, entity-agnostic)
    # =========================================================================
    op.create_table(
        "document_store",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("storage_backend", sa.String(50), nullable=False, server_default="s3"),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("document_type", sa.String(50), nullable=False, server_default="supporting"),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("uploaded_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        comment="Generic document metadata for uploaded files",
        if_not_exists=True,
    )
    _idx("ix_document_store_storage_key", "document_store", ["storage_key"])
    _idx("ix_document_store_uploaded_by", "document_store", ["uploaded_by"])
    _idx("ix_document_store_mime_type", "document_store", ["mime_type"])
    _idx("ix_document_store_created_at", "document_store", ["created_at"])
    _idx("ix_document_store_file_hash", "document_store", ["file_hash"])

    # =========================================================================
    # document_links  (polymorphic associations for document_store)
    # =========================================================================
    op.create_table(
        "document_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("document_store.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="supporting"),
        sa.Column("associated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("associated_by", sa.String(255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        comment="Polymorphic document-entity associations",
        if_not_exists=True,
    )
    _uidx(
        "uq_document_links_source_document",
        "document_links",
        ["source_type", "source_id", "document_id"],
    )
    _idx("ix_document_links_source_type", "document_links", ["source_type"])
    _idx("ix_document_links_source_id", "document_links", ["source_id"])
    _idx("ix_document_links_document_id", "document_links", ["document_id"])
    _idx("ix_document_links_role", "document_links", ["role"])


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table("document_links")
    op.drop_table("document_store")
    op.drop_table("plan_sessions")
    op.drop_table("indexing_progress")
    op.drop_table("embedding_progress")
    op.drop_table("failed_embedding_chunks")
    op.drop_table("pending_chunks")
    op.drop_table("file_index")
    op.drop_table("user_preferences")
    op.drop_table("documents")
    op.drop_table("repositories")
