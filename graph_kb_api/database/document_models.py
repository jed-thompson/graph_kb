"""SQLAlchemy ORM models for the generic document system.

Provides entity-agnostic document storage and polymorphic associations
via source_type + source_id (Discourse/Redmine pattern).

- documents: Generic file metadata (no entity FKs)
- document_links: Polymorphic associations to any entity type
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from graph_kb_api.database.base import Base


class UploadedDocument(Base):
    """Generic file metadata for uploaded documents.

    Entity-agnostic: stores storage reference, file metadata, and
    deduplication hash. No foreign keys to any entity table.
    """

    __tablename__ = "document_store"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(50), nullable=False, server_default="s3")
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="supporting")
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    links: Mapped[List["DocumentLink"]] = relationship(
        "DocumentLink", back_populates="uploaded_document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_document_store_storage_key", "storage_key"),
        Index("ix_document_store_uploaded_by", "uploaded_by"),
        Index("ix_document_store_mime_type", "mime_type"),
        Index("ix_document_store_created_at", "created_at"),
        Index("ix_document_store_file_hash", "file_hash"),
        {"comment": "Generic document metadata for uploaded files"},
    )

    def __repr__(self) -> str:
        return f"<UploadedDocument(id='{self.id}', filename='{self.original_filename}')>"


class DocumentLink(Base):
    """Polymorphic association linking documents to any entity type.

    Uses source_type + source_id (no FK on source_id) so the same
    table can link documents to plan sessions, repositories, chats, etc.
    Adding a new entity type requires zero schema changes.
    """

    __tablename__ = "document_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement="auto")
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_store.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, server_default="supporting")
    associated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    associated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    uploaded_document: Mapped["UploadedDocument"] = relationship("UploadedDocument", back_populates="links")

    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "document_id",
            name="uq_document_links_source_document",
        ),
        Index("ix_document_links_source_type", "source_type"),
        Index("ix_document_links_source_id", "source_id"),
        Index("ix_document_links_document_id", "document_id"),
        Index("ix_document_links_role", "role"),
        {"comment": "Polymorphic document-entity associations"},
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentLink(source='{self.source_type}', "
            f"source_id='{self.source_id}', document_id='{self.document_id}')>"
        )
