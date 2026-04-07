"""Plan session REST API router.

Provides endpoints for listing, retrieving, and deleting plan sessions
so the frontend can show a session picker for browser-close resume.
"""

import asyncio
import hashlib
import io
import logging
import re
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import Result, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from graph_kb_api.database.document_models import DocumentLink, UploadedDocument
from graph_kb_api.database.document_repositories import (
    DocumentLinkRepository,
    DocumentRepository,
)
from graph_kb_api.database.plan_models import PlanSession
from graph_kb_api.database.plan_repositories import PlanSessionRepository
from graph_kb_api.dependencies import get_db_session
from graph_kb_api.schemas.plan import (
    PlanDocumentListResponse,
    PlanDocumentResponse,
    PlanDocumentUploadResponse,
    PlanSessionDeleteResponse,
    PlanSessionDetailResponse,
    PlanSessionListResponse,
    PlanSessionUpdateRequest,
    PlanSessionUpdateResponse,
)
from graph_kb_api.storage import Artifact
from graph_kb_api.storage.blob_storage import BlobStorage

MAX_PLAN_FILE_SIZE = 50 * 1024 * 1024  # 50MB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plan/sessions", tags=["Plan Sessions"])


def _get_repo(db: AsyncSession = Depends(get_db_session)) -> PlanSessionRepository:
    return PlanSessionRepository(db)


@router.get("", response_model=PlanSessionListResponse)
async def list_plan_sessions(
    user_id: str | None = Query(None, description="User ID to filter sessions (omit for all)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    repo: PlanSessionRepository = Depends(_get_repo),
) -> PlanSessionListResponse:
    """List plan sessions, optionally filtered by user_id."""
    if user_id:
        sessions: list[PlanSession] = await repo.list_by_user(user_id, limit=limit, offset=offset)
        total_result = await repo._execute(
            select(func.count(PlanSession.id)).where(PlanSession.user_id == user_id),
        )
    else:
        sessions = await repo.list_all(limit=limit, offset=offset)
        total_result = await repo._execute(select(func.count(PlanSession.id)))
    total = total_result.scalar_one()
    return PlanSessionListResponse(
        sessions=[PlanSessionDetailResponse.model_validate(s) for s in sessions],
        total=total,
    )


@router.get("/{session_id}", response_model=PlanSessionDetailResponse)
async def get_plan_session(
    session_id: str,
    repo: PlanSessionRepository = Depends(_get_repo),
) -> PlanSessionDetailResponse:
    """Get full details for a single plan session."""
    session: PlanSession | None = await repo.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return PlanSessionDetailResponse.model_validate(session)


@router.patch("/{session_id}", response_model=PlanSessionUpdateResponse)
async def update_plan_session(
    session_id: str,
    body: PlanSessionUpdateRequest,
    repo: PlanSessionRepository = Depends(_get_repo),
) -> PlanSessionUpdateResponse:
    """Update a plan session (e.g. rename it)."""
    updated: PlanSession | None = await repo.update(session_id, name=body.name)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return PlanSessionUpdateResponse.model_validate(updated)


@router.delete("/{session_id}", response_model=PlanSessionDeleteResponse)
async def delete_plan_session(
    session_id: str,
    repo: PlanSessionRepository = Depends(_get_repo),
) -> PlanSessionDeleteResponse:
    """Delete a plan session and its checkpoint."""
    deleted: bool = await repo.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return PlanSessionDeleteResponse(success=True, session_id=session_id)


# ── Artifact Retrieval ─────────────────────────────────────────────


class PlanArtifactResponse(BaseModel):
    """Response for a plan artifact."""

    content: str
    content_type: str = "text/plain"


class PlanArtifactManifestEntryResponse(BaseModel):
    """List entry for a stored plan artifact."""

    key: str
    summary: str
    size_bytes: int
    created_at: str
    content_type: str


class PlanArtifactListResponse(BaseModel):
    """Response listing artifacts stored for a plan session."""

    artifacts: list[PlanArtifactManifestEntryResponse]
    total: int


def _artifact_summary_from_key(artifact_key: str) -> str:
    """Build a human-readable label from an artifact storage key."""

    path = PurePosixPath(artifact_key)
    stem = path.stem or path.name or artifact_key
    cleaned = re.sub(r"[_-]+", " ", stem).strip()
    if not cleaned:
        cleaned = artifact_key
    return cleaned[:1].upper() + cleaned[1:]


@router.get("/{session_id}/artifacts", response_model=PlanArtifactListResponse)
async def list_plan_artifacts(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> PlanArtifactListResponse:
    """List stored workflow artifacts for a plan session."""
    try:
        plan_repo = PlanSessionRepository(db)
        session: PlanSession | None = await plan_repo.get(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan session not found",
            )

        storage: BlobStorage = BlobStorage.from_env()
        prefix = f"specs/{session_id}/"
        stored_paths = await storage.backend.list_directory(prefix)

        artifacts: list[PlanArtifactManifestEntryResponse] = []
        for stored_path in stored_paths:
            if not stored_path.startswith(prefix):
                continue

            artifact_key = stored_path[len(prefix):].strip("/")
            if not artifact_key:
                continue

            artifact = await storage.backend.retrieve(stored_path)
            if artifact is None:
                continue

            artifacts.append(
                PlanArtifactManifestEntryResponse(
                    key=artifact_key,
                    summary=_artifact_summary_from_key(artifact_key),
                    size_bytes=artifact.size_bytes,
                    created_at=artifact.created_at.isoformat(),
                    content_type=artifact.content_type,
                )
            )

        artifacts.sort(key=lambda artifact: artifact.created_at, reverse=True)
        return PlanArtifactListResponse(artifacts=artifacts, total=len(artifacts))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list plan artifacts for session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list artifacts: {e}",
        )


@router.get("/{session_id}/artifacts/{artifact_key:path}", response_model=PlanArtifactResponse)
async def get_plan_artifact(
    session_id: str,
    artifact_key: str,
) -> PlanArtifactResponse:
    """Retrieve a plan artifact by key.

    The artifact key maps to the blob path ``specs/{session_id}/{artifact_key}``,
    following the same convention used by ``ArtifactService.store()``.

    Args:
        session_id: Plan session UUID.
        artifact_key: Dot-delimited artifact key (e.g. ``context.reference_0``).

    Returns:
        The artifact content and content type.
    """
    if not re.match(r"^[a-zA-Z0-9._/-]+$", artifact_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid artifact key format",
        )

    key = f"specs/{session_id}/{artifact_key}"

    try:
        storage: BlobStorage = BlobStorage.from_env()
        artifact: Artifact | None = await storage.backend.retrieve(key)
        if artifact is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact not found: {artifact_key}",
            )
        return PlanArtifactResponse(
            content=str(artifact.content) if artifact.content is not None else "",
            content_type=artifact.content_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to retrieve plan artifact %s: %s", artifact_key, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve artifact: {e}",
        )


# ── Plan Document Management ─────────────────────────────────────


@router.post("/{session_id}/documents", response_model=PlanDocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_plan_document(
    session_id: str,
    file: UploadFile = File(...),
    document_type: str = Form("supporting"),
    db: AsyncSession = Depends(get_db_session),
) -> PlanDocumentUploadResponse:
    """Upload a document for a plan session.

    Supports deduplication via SHA-256 hash - if a file with the same hash
    already exists in the session, the existing document is returned instead.
    """
    try:
        return await _upload_plan_document_impl(session_id, file, document_type, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to upload plan document: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload document: {e}",
        )


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from PDF bytes using pypdf.

    Runs synchronously — callers should use ``run_in_executor`` to avoid
    blocking the event loop.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


async def _upload_plan_document_impl(
    session_id: str,
    file: UploadFile,
    document_type: str,
    db: AsyncSession,
) -> PlanDocumentUploadResponse:
    # Validate session exists
    plan_repo = PlanSessionRepository(db)
    session = await plan_repo.get(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plan session not found",
        )

    # Validate file size
    contents: bytes = await file.read()
    if len(contents) > MAX_PLAN_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum of {MAX_PLAN_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Compute SHA-256 hash for deduplication (always from original bytes)
    file_hash: str = hashlib.sha256(contents).hexdigest()

    # Extract text from PDFs at upload time so downstream readers can use the content
    effective_mime: str = file.content_type or "application/octet-stream"
    filename_lower = (file.filename or "").lower()
    if effective_mime == "application/pdf" or filename_lower.endswith(".pdf"):
        try:
            loop = asyncio.get_event_loop()
            extracted = await loop.run_in_executor(None, _extract_pdf_text, contents)
            if extracted.strip():
                contents = extracted.encode("utf-8")
                effective_mime = "text/plain"
                logger.info(
                    "PDF text extraction: %s → %d chars", file.filename, len(extracted)
                )
            else:
                logger.warning(
                    "PDF text extraction yielded no text for %s — storing original",
                    file.filename,
                )
        except Exception as exc:
            logger.warning(
                "PDF text extraction failed for %s: %s — storing original",
                file.filename,
                exc,
            )

    # Check for duplicate in this session (single JOIN query)
    doc_repo = DocumentRepository(db)
    assoc_repo = DocumentLinkRepository(db)

    dup_stmt: Select[tuple[UploadedDocument]] = (
        select(UploadedDocument)
        .join(DocumentLink, DocumentLink.document_id == UploadedDocument.id)
        .where(
            DocumentLink.source_type == "plan_session",
            DocumentLink.source_id == session_id,
            UploadedDocument.file_hash == file_hash,
        )
    )
    dup_result: Result[tuple[UploadedDocument]] = await db.execute(dup_stmt)
    duplicate: UploadedDocument | None = dup_result.scalar_one_or_none()
    if duplicate:
        logger.info("Found duplicate document %s with same hash for session %s", duplicate.id, session_id)
        return PlanDocumentUploadResponse(
            id=duplicate.id,
            original_filename=duplicate.original_filename,
            mime_type=duplicate.mime_type,
            file_size=duplicate.file_size,
            document_type=duplicate.document_type,
        )

    # No duplicate found - create new document
    storage: BlobStorage = BlobStorage.from_env()

    # Generate unique ID and storage path
    doc_id = str(uuid.uuid4())
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else ""
    storage_key = f"plan_docs/{session_id}/{doc_id}.{ext}"

    # Store file in blob storage
    await storage.backend.store(
        path=storage_key,
        content=contents,
        content_type=effective_mime,
    )

    # Create document record
    document = await doc_repo.create(
        storage_key=storage_key,
        original_filename=file.filename or "unnamed",
        mime_type=effective_mime,
        file_size=len(contents),
        file_hash=file_hash,
        document_type=document_type,
        uploaded_by=session.user_id,
    )

    # Create association with plan session
    await assoc_repo.associate(
        source_type="plan_session",
        source_id=session_id,
        document_id=document.id,
        role="supporting",
        associated_by=session.user_id,
    )

    logger.info(f"Uploaded document {document.id} for plan session {session_id}")
    return PlanDocumentUploadResponse(
        id=document.id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        file_size=document.file_size,
        document_type=document.document_type,
    )


@router.get("/{session_id}/documents", response_model=PlanDocumentListResponse)
async def list_plan_documents(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> PlanDocumentListResponse:
    """List all documents for a plan session."""
    try:
        # Validate session exists
        plan_repo = PlanSessionRepository(db)
        session: PlanSession | None = await plan_repo.get(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan session not found",
            )

        # Fetch documents with a single JOIN query (exclude soft-deleted)
        stmt: Select[tuple[UploadedDocument]] = (
            select(UploadedDocument)
            .join(DocumentLink, DocumentLink.document_id == UploadedDocument.id)
            .where(
                DocumentLink.source_type == "plan_session",
                DocumentLink.source_id == session_id,
                UploadedDocument.deleted_at.is_(None),
            )
        )
        result: Result[tuple[UploadedDocument]] = await db.execute(stmt)
        documents: list[PlanDocumentResponse] = [
            PlanDocumentResponse.model_validate(doc) for doc in result.scalars().all()
        ]

        return PlanDocumentListResponse(
            documents=documents,
            total=len(documents),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list plan documents for session %s: %s", session_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {e}",
        )


@router.get("/{session_id}/documents/{doc_id}")
async def download_plan_document(
    session_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Download a document by ID.

    The document must be associated with the specified plan session.
    """
    try:
        # Validate session exists
        plan_repo = PlanSessionRepository(db)
        session: PlanSession | None = await plan_repo.get(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan session not found",
            )

        # Get document
        doc_repo = DocumentRepository(db)
        document: UploadedDocument | None = await doc_repo.get(doc_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        # Verify document is associated with this plan session (single query)
        assoc_stmt: Select[tuple[DocumentLink]] = select(DocumentLink).where(
            DocumentLink.source_type == "plan_session",
            DocumentLink.source_id == session_id,
            DocumentLink.document_id == doc_id,
        )
        assoc: DocumentLink | None = (await db.execute(assoc_stmt)).scalar_one_or_none()
        if not assoc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Document not associated with this plan session",
            )

        # Retrieve from blob storage
        storage: BlobStorage = BlobStorage.from_env()
        blob: Artifact | None = await storage.backend.retrieve(document.storage_key)

        if not blob:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in storage",
            )

        # Return file with appropriate headers
        return Response(
            content=blob.content,
            media_type=blob.content_type or document.mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{document.original_filename}"',
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to download plan document %s: %s", doc_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download document: {e}",
        )


@router.delete("/{session_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan_document(
    session_id: str,
    doc_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a plan document association and its blob.

    Removes the plan-session association. If no other sessions reference
    the document, the spec_document row and blob are also cleaned up.
    """
    try:
        # Validate session exists
        plan_repo = PlanSessionRepository(db)
        session: PlanSession | None = await plan_repo.get(session_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan session not found",
            )

        # Verify document exists and is associated with this plan session
        assoc_repo = DocumentLinkRepository(db)
        doc_repo = DocumentRepository(db)

        document: UploadedDocument | None = await doc_repo.get(doc_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        assoc_stmt: Select[tuple[DocumentLink]] = select(DocumentLink).where(
            DocumentLink.source_type == "plan_session",
            DocumentLink.source_id == session_id,
            DocumentLink.document_id == doc_id,
        )
        assoc: DocumentLink | None = (await db.execute(assoc_stmt)).scalar_one_or_none()
        if not assoc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Document not associated with this plan session",
            )

        # Remove plan association
        await assoc_repo.disassociate("plan_session", session_id, doc_id)

        # Check if any other associations remain for this document
        all_associations: list[DocumentLink] = await assoc_repo.list_by_document(doc_id)
        if not all_associations:
            # No other references — safe to remove document + blob
            try:
                storage: BlobStorage = BlobStorage.from_env()
                await storage.backend.delete(document.storage_key)
            except Exception as e:
                logger.warning("Failed to delete blob %s: %s", document.storage_key, e)
            await doc_repo._execute(delete(UploadedDocument).where(UploadedDocument.id == doc_id))
            await db.flush()

        logger.info(f"Deleted document {doc_id} from plan session {session_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete plan document %s: %s", doc_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {e}",
        )
