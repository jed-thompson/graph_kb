"""Async repository pattern classes for the generic document system.

- DocumentRepository: Document metadata CRUD (documents table)
- DocumentLinkRepository: Polymorphic document-entity associations (document_links table)
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from graph_kb_api.database.base import DatabaseError
from graph_kb_api.database.document_models import DocumentLink, UploadedDocument
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class DocumentRepository:
    """Repository for generic document metadata."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _execute(self, query) -> Any:
        try:
            result = await self.session.execute(query)
            return result
        except Exception as e:
            logger.error(f"Document query failed: {e}")
            raise DatabaseError(f"Database query failed: {e}", original=e) from e

    async def create(
        self,
        storage_key: str,
        original_filename: str,
        mime_type: str,
        file_size: int,
        uploaded_by: str,
        storage_backend: str = "s3",
        document_type: str = "supporting",
        file_hash: Optional[str] = None,
        category: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        document_id: Optional[str] = None,
    ) -> UploadedDocument:
        """Create a new document record."""
        now = datetime.now(UTC)
        document_id = document_id or str(uuid.uuid4())

        document = UploadedDocument(
            id=document_id,
            storage_key=storage_key,
            storage_backend=storage_backend,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            file_hash=file_hash,
            document_type=document_type,
            category=category,
            uploaded_by=uploaded_by,
            created_at=now,
            updated_at=now,
            metadata_json=metadata,
        )

        self.session.add(document)
        await self.session.flush()
        logger.info(f"Created document: {document_id}")
        return document

    async def get(self, document_id: str) -> Optional[UploadedDocument]:
        """Get a document by ID."""
        result = await self._execute(
            select(UploadedDocument).where(UploadedDocument.id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_by_storage_key(self, storage_key: str) -> Optional[UploadedDocument]:
        """Get a document by storage key."""
        result = await self._execute(
            select(UploadedDocument).where(UploadedDocument.storage_key == storage_key)
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, file_hash: str) -> Optional[UploadedDocument]:
        """Get a document by file hash (for deduplication)."""
        result = await self._execute(
            select(UploadedDocument).where(
                UploadedDocument.file_hash == file_hash,
                UploadedDocument.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def hard_delete(self, document_id: str) -> bool:
        """Permanently delete a document record."""
        result = await self._execute(
            delete(UploadedDocument).where(UploadedDocument.id == document_id)
        )
        return result.rowcount > 0

    async def soft_delete(self, document_id: str) -> bool:
        """Mark a document as deleted (soft delete)."""
        doc = await self.get(document_id)
        if doc:
            doc.deleted_at = datetime.now(UTC)
            await self.session.flush()
            return True
        return False

    async def exists(self, document_id: str) -> bool:
        """Check if a document exists without loading the full record."""
        result = await self._execute(
            select(UploadedDocument.id).where(
                UploadedDocument.id == document_id,
                UploadedDocument.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None


class DocumentLinkRepository:
    """Repository for polymorphic document-entity associations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _execute(self, query) -> Any:
        try:
            result = await self.session.execute(query)
            return result
        except Exception as e:
            logger.error(f"Document link query failed: {e}")
            raise DatabaseError(f"Database query failed: {e}", original=e) from e

    async def associate(
        self,
        source_type: str,
        source_id: str,
        document_id: str,
        role: str,
        associated_by: str,
        notes: Optional[str] = None,
    ) -> DocumentLink:
        """Associate a document with any entity type."""
        now = datetime.now(UTC)
        link = DocumentLink(
            document_id=document_id,
            source_type=source_type,
            source_id=source_id,
            role=role,
            associated_at=now,
            associated_by=associated_by,
            notes=notes,
        )
        self.session.add(link)
        await self.session.flush()
        logger.info(
            f"Associated document {document_id} with "
            f"{source_type}/{source_id}"
        )
        return link

    async def disassociate(
        self,
        source_type: str,
        source_id: str,
        document_id: str,
    ) -> bool:
        """Remove a document association."""
        result = await self._execute(
            delete(DocumentLink).where(
                DocumentLink.source_type == source_type,
                DocumentLink.source_id == source_id,
                DocumentLink.document_id == document_id,
            )
        )
        return result.rowcount > 0

    async def get_association(
        self,
        source_type: str,
        source_id: str,
        document_id: str,
    ) -> Optional[DocumentLink]:
        """Get a specific document association."""
        result = await self._execute(
            select(DocumentLink).where(
                DocumentLink.source_type == source_type,
                DocumentLink.source_id == source_id,
                DocumentLink.document_id == document_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_source(
        self,
        source_type: str,
        source_id: str,
    ) -> List[DocumentLink]:
        """List all document associations for a source entity."""
        result = await self._execute(
            select(DocumentLink)
            .where(
                DocumentLink.source_type == source_type,
                DocumentLink.source_id == source_id,
            )
            .order_by(DocumentLink.associated_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_document(self, document_id: str) -> List[DocumentLink]:
        """List all associations for a document across all sources."""
        result = await self._execute(
            select(DocumentLink).where(
                DocumentLink.document_id == document_id,
            )
        )
        return list(result.scalars().all())
