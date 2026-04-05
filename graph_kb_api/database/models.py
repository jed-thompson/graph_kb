"""SQLAlchemy ORM models for GraphKB metadata.

This module contains ORM models for all 8 tables that were previously
in the SQLite metadata_store.py:

- repositories
- documents
- file_index
- pending_chunks
- failed_embedding_chunks
- embedding_progress
- indexing_progress
- user_preferences

All models use async PostgreSQL with proper type mapping and relationships.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON as JSONB,
)
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from graph_kb_api.database.base import Base

# =========================================================================
# Table Models
# =========================================================================
# Note: Using String columns for status fields for simplicity and portability


# =========================================================================
# Table Models
# =========================================================================


class Repository(Base):
    """Repository metadata and indexing status.

    Maps to SQLite table: repositories
    """

    __tablename__ = "repositories"

    # Primary key
    repo_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Core fields
    git_url: Mapped[str] = mapped_column(String(500), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False)
    local_path: Mapped[str] = mapped_column(String(500), nullable=False)

    # Indexing fields
    last_indexed_commit: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata (for auditing)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # New: Indexing phase field
    indexing_phase: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, server_default="indexing"
    )

    # Relationships
    file_index_entries: Mapped[list["FileIndex"]] = relationship(
        "FileIndex", back_populates="repository", cascade="all, delete-orphan"
    )
    embedding_progress: Mapped["EmbeddingProgress"] = relationship(
        "EmbeddingProgress",
        back_populates="repository",
        uselist=False,
        cascade="all, delete-orphan",
    )
    indexing_progress: Mapped["IndexingProgress"] = relationship(
        "IndexingProgress",
        back_populates="repository",
        uselist=False,
        cascade="all, delete-orphan",
    )
    pending_chunks: Mapped[list["PendingChunk"]] = relationship(
        "PendingChunk", back_populates="repository", cascade="all, delete-orphan"
    )
    failed_chunks: Mapped[list["FailedEmbeddingChunk"]] = relationship(
        "FailedEmbeddingChunk",
        back_populates="repository",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Repository(repo_id='{self.repo_id}', status='{self.status}')>"


class Document(Base):
    """Document metadata and ingestion status.

    Maps to SQLite table: documents
    """

    __tablename__ = "documents"

    # Primary key
    doc_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Core fields
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    parent_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    collection_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Status fields
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # S3 storage fields
    s3_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    s3_bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Document(doc_id='{self.doc_id}', status='{self.status}')>"


class FileIndex(Base):
    """File indexing status for checkpoint/resume tracking.

    Maps to SQLite table: file_index
    """

    __tablename__ = "file_index"

    # Composite primary key: (repo_id, file_path)
    repo_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("repositories.repo_id"),
        primary_key=True,
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(
        String(1000), primary_key=True, nullable=False
    )

    # Indexing fields
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    symbol_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="file_index_entries"
    )

    def __repr__(self) -> str:
        return f"<FileIndex(repo_id='{self.repo_id}', file_path='{self.file_path}')>"


class PendingChunk(Base):
    """Chunks awaiting embedding.

    Maps to SQLite table: pending_chunks

    Note: SQLite uses INTEGER AUTOINCREMENT for id, but PostgreSQL
    will use a SERIAL or BIGSERIAL for auto-generated IDs.
    """

    __tablename__ = "pending_chunks"

    # Primary key (auto-generated)
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement="auto",  # PostgreSQL SERIAL
    )

    # Core fields
    repo_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("repositories.repo_id"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # JSON fields (stored as JSONB in PostgreSQL)
    metadata_json: Mapped[Optional[str]] = mapped_column(JSONB, nullable=True)
    symbol_ids_json: Mapped[Optional[str]] = mapped_column(JSONB, nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("repo_id", "chunk_id", name="uq_pending_chunks_repo_chunk"),
        {"comment": "Stores chunks between indexing and embedding phases"},
    )

    # Relationship
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="pending_chunks"
    )

    def __repr__(self) -> str:
        return f"<PendingChunk(id={self.id}, chunk_id='{self.chunk_id}')>"


class FailedEmbeddingChunk(Base):
    """Chunks that failed during embedding for retry.

    Maps to SQLite table: failed_embedding_chunks
    """

    __tablename__ = "failed_embedding_chunks"

    # Primary key (auto-generated)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement="auto")

    # Core fields
    repo_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("repositories.repo_id"), nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # JSON fields
    metadata_json: Mapped[Optional[str]] = mapped_column(JSONB, nullable=True)
    symbol_ids_json: Mapped[Optional[str]] = mapped_column(JSONB, nullable=True)

    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_retry_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Unique constraint
    __table_args__ = (
        UniqueConstraint("repo_id", "chunk_id", name="uq_failed_chunks_repo_chunk"),
        {"comment": "Stores chunks that failed during embedding for retry"},
    )

    # Relationship
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="failed_chunks"
    )

    def __repr__(self) -> str:
        return f"<FailedEmbeddingChunk(id={self.id}, chunk_id='{self.chunk_id}', retry_count={self.retry_count})>"


class EmbeddingProgress(Base):
    """Embedding progress tracking for a repository.

    Maps to SQLite table: embedding_progress
    """

    __tablename__ = "embedding_progress"

    # Primary key
    repo_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("repositories.repo_id"),
        primary_key=True,
        nullable=False,
    )

    # Progress fields
    total_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    embedded_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    failed_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    skipped_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    current_chunk_idx: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    # Metadata
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="embedding_progress"
    )

    def __repr__(self) -> str:
        return f"<EmbeddingProgress(repo_id='{self.repo_id}', embedded={self.embedded_chunks}/{self.total_chunks})>"


class IndexingProgress(Base):
    """Live indexing progress for page refreshes.

    Maps to SQLite table: indexing_progress
    """

    __tablename__ = "indexing_progress"

    # Primary key
    repo_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("repositories.repo_id"),
        primary_key=True,
        nullable=False,
    )

    # Progress fields
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    total_files: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    processed_files: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    current_file: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    total_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_symbols: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_relationships: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    embedded_chunks: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    total_chunks_to_embed: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadata
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationship
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="indexing_progress"
    )

    def __repr__(self) -> str:
        return f"<IndexingProgress(repo_id='{self.repo_id}', phase='{self.phase}')>"


class UserPreference(Base):
    """User retrieval preferences.

    Maps to SQLite table: user_preferences
    """

    __tablename__ = "user_preferences"

    # Primary key
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Settings (stored as JSON)
    settings_json: Mapped[str] = mapped_column(JSONB, nullable=False)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return f"<UserPreference(user_id='{self.user_id}')>"
