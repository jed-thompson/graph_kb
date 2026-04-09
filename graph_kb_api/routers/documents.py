"""
Document management router.

Provides endpoints for listing, retrieving, uploading, and deleting
documents stored in ChromaDB and S3/MinIO blob storage.

Upload behavior:
- All documents are stored in S3/MinIO blob storage
- By default, documents are also indexed in ChromaDB for semantic search
- Set index_for_search=False to skip ChromaDB indexing (S3-only storage)
"""

import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Response, UploadFile

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.schemas.documents import (
    DocumentFilterOptions,
    DocumentListResponse,
    DocumentResponse,
    DocumentUpdateRequest,
)
from graph_kb_api.storage.blob_storage import BlobStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/docs", tags=["Documents"])

# Configuration
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB default max file size
PRESIGNED_URL_EXPIRY = 3600  # 1 hour default expiry for pre-signed URLs


def _ensure_vector_store(facade):
    """Return the vector store or raise 503 if unavailable."""
    if facade.vector_store is None:
        raise HTTPException(
            status_code=503,
            detail="ChromaDB vector store is unavailable",
        )
    return facade.vector_store


@router.get("/filter-options", response_model=DocumentFilterOptions)
async def get_filter_options(
    facade=Depends(get_graph_kb_facade),
):
    """Get distinct values for filtering documents (parents and categories)."""
    try:
        parents: set[str] = set()
        categories: set[str] = set()

        # Primary source: blob storage metadata (source of truth for user uploads)
        try:
            bs = BlobStorage.from_env()
            blob_items = await bs.backend.list_with_metadata("documents/")
            for item in blob_items:
                meta = item.get("metadata", {})
                parent = meta.get("parent") or None
                category = meta.get("category") or None
                if parent:
                    parents.add(parent)
                if category:
                    categories.add(category)
        except Exception as e:
            logger.warning(f"Blob storage filter-options listing failed: {e}")

        # Secondary source: ChromaDB (picks up pre-blob indexed docs and repo chunks)
        try:
            vector_store = _ensure_vector_store(facade)
            results = vector_store.collection.get(include=["metadatas"])
            for meta in results.get("metadatas", []):
                if meta:
                    parent = meta.get("parent") or meta.get("repo_id")
                    if parent:
                        parents.add(parent)
                    if meta.get("category"):
                        categories.add(meta["category"])
        except HTTPException:
            pass  # ChromaDB unavailable — blob results are sufficient
        except Exception as e:
            logger.warning(f"ChromaDB filter-options listing failed: {e}")

        return DocumentFilterOptions(
            parents=sorted(parents),
            categories=sorted(categories),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get filter options: {e}")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    parent: Optional[str] = Query(None, description="Filter by parent document"),
    category: Optional[str] = Query(None, description="Filter by category"),
    user_uploads_only: bool = Query(True, description="Only return user-uploaded documents (not repo chunks)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit"),
    facade=Depends(get_graph_kb_facade),
):
    """List documents with optional filtering and pagination.

    Blob storage is the source of truth for user-uploaded documents.
    ChromaDB is queried to add indexed_for_search status and as a fallback
    for any docs not yet in blob storage.
    Set user_uploads_only=false to also include repo code chunks from ChromaDB.
    """
    try:
        docs: Dict[str, DocumentResponse] = {}

        # --- Primary source: blob storage ---
        try:
            bs = BlobStorage.from_env()
            blob_items = await bs.backend.list_with_metadata("documents/")
            for item in blob_items:
                meta = item.get("metadata", {})
                doc_id = meta.get("doc_id")
                if not doc_id:
                    continue
                item_parent = meta.get("parent") or None
                item_category = meta.get("category") or None
                if parent and item_parent != parent:
                    continue
                if category and item_category != category:
                    continue
                file_size_raw = meta.get("file_size")
                try:
                    file_size = int(file_size_raw) if file_size_raw else None
                except (ValueError, TypeError):
                    file_size = None
                docs[doc_id] = DocumentResponse(
                    id=doc_id,
                    filename=meta.get("original_filename") or meta.get("filename", ""),
                    parent=item_parent,
                    category=item_category,
                    content=None,
                    metadata=meta,
                    created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                    storage_key=item["path"],
                    indexed_for_search=False,
                    file_size=file_size,
                    mime_type=meta.get("mime_type"),
                )
        except Exception as e:
            logger.warning(f"Blob storage listing failed: {e}")

        # --- Secondary: ChromaDB (indexed status + fallback for pre-blob docs) ---
        try:
            vector_store = _ensure_vector_store(facade)
            chroma_results = vector_store.collection.get(include=["metadatas", "documents"])
            all_ids = chroma_results.get("ids", [])
            all_metadatas = chroma_results.get("metadatas", [])
            all_documents = chroma_results.get("documents", [])

            for i, doc_id in enumerate(all_ids):
                meta = all_metadatas[i] if all_metadatas else {}
                content = all_documents[i] if all_documents else None

                if doc_id in docs:
                    # Mark blob doc as indexed; backfill fields missing from old blob metadata
                    docs[doc_id].indexed_for_search = True
                    if content:
                        docs[doc_id].content = content
                    if meta:
                        if not docs[doc_id].category and meta.get("category"):
                            docs[doc_id].category = meta.get("category")
                        if not docs[doc_id].parent and meta.get("parent"):
                            docs[doc_id].parent = meta.get("parent")
                    continue

                # Fallback: ChromaDB-only doc not yet in blob storage
                has_storage_key = meta and meta.get("storage_key")
                has_filename_no_repo = meta and meta.get("filename") and not meta.get("repo_id")
                is_user_upload = has_storage_key or has_filename_no_repo
                if user_uploads_only and not is_user_upload:
                    continue

                item_parent = (meta.get("parent") or meta.get("repo_id")) if meta else None
                item_category = meta.get("category") if meta else None
                if parent and item_parent != parent:
                    continue
                if category and item_category != category:
                    continue

                docs[doc_id] = DocumentResponse(
                    id=doc_id,
                    filename=(meta.get("filename") or meta.get("file_path") or doc_id) if meta else doc_id,
                    parent=item_parent,
                    category=item_category,
                    content=content,
                    metadata=meta,
                    created_at=(meta.get("created_at") or datetime.now(timezone.utc).isoformat()) if meta else datetime.now(timezone.utc).isoformat(),
                    storage_key=meta.get("storage_key") if meta else None,
                    indexed_for_search=True,
                    file_size=meta.get("file_size") if meta else None,
                    mime_type=meta.get("mime_type") if meta else None,
                )
        except Exception as e:
            logger.warning(f"ChromaDB listing failed: {e}")
            if not docs:
                raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")

        all_docs = sorted(docs.values(), key=lambda d: str(d.created_at or ""), reverse=True)
        total = len(all_docs)
        page_docs = all_docs[offset : offset + limit]

        logger.info(f"Listed {total} documents ({sum(1 for d in all_docs if d.indexed_for_search)} indexed)")

        return DocumentListResponse(
            documents=page_docs,
            total=total,
            offset=offset,
            limit=limit,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: str,
    facade=Depends(get_graph_kb_facade),
):
    """Get a single document by ID with its content and metadata.

    Tries ChromaDB first (indexed docs), then falls back to blob storage
    (non-indexed / blob-only docs). PDFs are extracted via pypdf.
    """
    try:
        # Primary: ChromaDB (indexed docs)
        if facade.vector_store:
            result = facade.vector_store.get(doc_id)
            if result:
                meta = result.metadata or {}
                filename = meta.get("filename") or meta.get("file_path") or result.chunk_id
                return DocumentResponse(
                    id=result.chunk_id,
                    filename=filename,
                    parent=meta.get("parent") or meta.get("repo_id"),
                    category=meta.get("category"),
                    content=result.content,
                    metadata=meta,
                    created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                )

        # Fallback: blob storage (non-indexed docs, including PDFs)
        try:
            bs = BlobStorage.from_env()
            blob_items = await bs.backend.list_with_metadata("documents/")
            target_item = next(
                (item for item in blob_items if item.get("metadata", {}).get("doc_id") == doc_id),
                None,
            )
        except Exception as blob_err:
            logger.warning(f"Blob storage lookup failed for {doc_id}: {blob_err}")
            target_item = None

        if not target_item:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        meta = target_item.get("metadata", {})
        storage_key = target_item["path"]
        filename = meta.get("original_filename") or doc_id

        content_str: Optional[str] = None
        try:
            bs = BlobStorage.from_env()
            result_binary = await bs.backend.retrieve_binary(storage_key)
            if result_binary:
                content_bytes, _ = result_binary
                is_pdf = filename.lower().endswith(".pdf") or meta.get("mime_type") == "application/pdf"
                if is_pdf:
                    try:
                        from pypdf import PdfReader
                        reader = PdfReader(io.BytesIO(content_bytes))
                        extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                        if extracted:
                            content_str = extracted
                    except Exception as pdf_err:
                        logger.warning(f"PDF text extraction failed for {doc_id}: {pdf_err}")
                else:
                    try:
                        content_str = content_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        pass
        except Exception as read_err:
            logger.warning(f"Failed to read blob content for {doc_id}: {read_err}")

        return DocumentResponse(
            id=doc_id,
            filename=filename,
            parent=meta.get("parent") or None,
            category=meta.get("category") or None,
            content=content_str,
            metadata=meta,
            created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get document: {e}")


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    parent: Optional[str] = Form(None),
    category: Optional[str] = Form(None, description="Category for the document"),
    force: bool = Form(False),
    index_for_search: bool = Form(True, description="Index document in ChromaDB for semantic search"),
    facade=Depends(get_graph_kb_facade),
):
    """Upload a document.

    All documents are stored in S3/MinIO blob storage.
    If index_for_search is True (default), the document is also indexed
    in ChromaDB for semantic search capabilities.

    If ``force`` is False and a document with the same filename already
    exists in ChromaDB, the upload is skipped and the existing document is returned.
    """
    try:
        filename = file.filename or "untitled"
        content_bytes = await file.read()
        mime_type = file.content_type or "application/octet-stream"

        # Validate file size
        file_size = len(content_bytes)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File size ({file_size} bytes) exceeds maximum allowed ({MAX_FILE_SIZE} bytes)",
            )

        doc_id = str(uuid.uuid4())
        now: datetime = datetime.now(timezone.utc)

        # Calculate file hash for deduplication
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        metadata = {
            "filename": filename,
            "created_at": now.isoformat(),
            "file_size": len(content_bytes),
            "mime_type": mime_type,
            "file_hash": file_hash,
        }
        if parent:
            metadata["parent"] = parent
        if category:
            metadata["category"] = category

        # Always store in S3/blob storage
        try:
            blob_storage: BlobStorage = BlobStorage.from_env()
            extension = Path(filename).suffix or ""
            storage_key = f"documents/{doc_id}{extension}"

            await blob_storage.backend.store_binary(
                path=storage_key,
                content=content_bytes,
                content_type=mime_type,
                metadata={
                    "doc_id": doc_id,
                    "original_filename": filename,
                    "parent": parent or "",
                    "category": category or "",
                    "created_at": now.isoformat(),
                    "file_size": str(len(content_bytes)),
                    "mime_type": mime_type,
                },
            )
            metadata["storage_key"] = storage_key
            logger.info(f"Stored document {doc_id} in blob storage at {storage_key}")
        except Exception as e:
            logger.warning(f"Failed to store document in blob storage: {e}")
            # Continue without blob storage - still index in ChromaDB

        # Optionally index in ChromaDB for semantic search
        if index_for_search:
            vector_store = _ensure_vector_store(facade)

            # Check for existing document with same filename when force=False
            if not force:
                try:
                    existing = vector_store.collection.get(
                        where={"filename": filename},
                        include=["metadatas", "documents"],
                    )
                    if existing and existing["ids"]:
                        logger.info(
                            f"Found existing document with filename '{filename}', returning existing doc {existing['ids'][0]}"
                        )
                        existing_meta = existing["metadatas"][0] if existing.get("metadatas") else {}
                        existing_content = existing["documents"][0] if existing.get("documents") else None
                        # Ensure storage_key is in metadata for display
                        if "storage_key" not in existing_meta:
                            logger.info("Existing doc missing storage_key, updating ChromaDB record")
                            existing_meta["storage_key"] = storage_key
                            # Update the ChromaDB record with the new metadata
                            vector_store.collection.update(
                                ids=[existing["ids"][0]],
                                metadatas=[existing_meta],
                            )

                        return DocumentResponse(
                            id=existing["ids"][0],
                            filename=filename,
                            parent=existing_meta.get("parent"),
                            category=existing_meta.get("category"),
                            content=existing_content,
                            metadata=existing_meta,
                            created_at=existing_meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                        )
                    else:
                        logger.debug(
                            f"No existing document found with filename '{filename}', proceeding with new upload"
                        )
                except Exception as e:
                    # If the where query fails (e.g. no metadata index), proceed with upload
                    logger.warning(f"Deduplication query failed for '{filename}': {e}, proceeding with upload")
                    pass

            # Try to decode as text for ChromaDB indexing
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # Try PDF text extraction before giving up
                content = None
                is_pdf = filename.lower().endswith(".pdf") or mime_type == "application/pdf"
                if is_pdf:
                    try:
                        from pypdf import PdfReader

                        reader = PdfReader(io.BytesIO(content_bytes))
                        content = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                        if not content:
                            content = None
                            logger.info(f"PDF {filename} had no extractable text; stored in S3 only (not indexed)")
                        else:
                            logger.info(f"Extracted {len(content)} chars of text from PDF {filename}")
                    except Exception as e:
                        logger.warning(f"PDF text extraction failed for {filename}: {e}")

                if content is None:
                    # Binary file with no extractable text - store only
                    logger.info(f"Binary file {filename} stored in S3 only (not indexed)")
                    metadata["indexed_for_search"] = False
                    return DocumentResponse(
                        id=doc_id,
                        filename=filename,
                        parent=parent,
                        category=category,
                        content=None,
                        metadata=metadata,
                        created_at=now,
                    )

            # Generate embedding
            embedding_generator = facade.embedding_generator
            if embedding_generator is None:
                raise HTTPException(
                    status_code=503,
                    detail="Embedding generator is unavailable",
                )
            embedding = embedding_generator.embed(content)

            vector_store.upsert(
                chunk_id=doc_id,
                embedding=embedding,
                metadata=metadata,
                content=content,
            )
            metadata["indexed_for_search"] = True
            logger.info(f"Successfully indexed document {doc_id} ({filename}) in ChromaDB")
        else:
            metadata["indexed_for_search"] = False

        # Return response with content if text, None if binary
        try:
            content_str = content_bytes.decode("utf-8") if index_for_search else None
        except UnicodeDecodeError:
            content_str = None

        return DocumentResponse(
            id=doc_id,
            filename=filename,
            parent=parent,
            category=category,
            content=content_str,
            metadata=metadata,
            created_at=now,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {e}")


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    use_presigned: bool = Query(False, description="Return pre-signed URL instead of content"),
    facade=Depends(get_graph_kb_facade),
):
    """Serve a document from blob storage for inline viewing or download.

    Tries ChromaDB first for storage_key metadata, then falls back to
    scanning blob storage directly (for non-indexed / blob-only docs).
    Returns content with Content-Disposition: inline so browsers render
    PDFs natively instead of prompting a download.
    """
    try:
        blob_storage: BlobStorage = BlobStorage.from_env()
        storage_key: Optional[str] = None
        filename: str = doc_id
        mime_type: str = "application/octet-stream"

        # Primary: resolve storage_key from ChromaDB metadata
        vector_store = facade.vector_store
        if vector_store:
            result = vector_store.get(doc_id)
            if result:
                meta = result.metadata or {}
                storage_key = meta.get("storage_key")
                filename = meta.get("filename", doc_id)
                mime_type = meta.get("mime_type", "application/octet-stream")

                # ChromaDB-only doc (no blob) — serve text content directly
                if not storage_key:
                    content_text = result.content
                    if not content_text:
                        raise HTTPException(
                            status_code=404,
                            detail="Document content not available (not stored in blob storage)",
                        )
                    return Response(
                        content=content_text.encode("utf-8"),
                        media_type=meta.get("mime_type", "text/plain"),
                        headers={"Content-Disposition": f'inline; filename="{filename}"'},
                    )

        # Fallback: scan blob storage metadata for matching doc_id
        if not storage_key:
            try:
                blob_items = await blob_storage.backend.list_with_metadata("documents/")
                target = next(
                    (item for item in blob_items if item.get("metadata", {}).get("doc_id") == doc_id),
                    None,
                )
            except Exception as scan_err:
                logger.warning(f"Blob scan failed for {doc_id}: {scan_err}")
                target = None

            if not target:
                raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

            meta = target.get("metadata", {})
            storage_key = target["path"]
            filename = meta.get("original_filename", doc_id)
            mime_type = meta.get("mime_type", "application/octet-stream")

        # Retrieve binary from blob storage
        result_binary = await blob_storage.backend.retrieve_binary(storage_key)
        if not result_binary:
            raise HTTPException(status_code=404, detail="Document file not found in storage")

        content, _ = result_binary

        # Handle pre-signed URL request
        if use_presigned:
            try:
                presigned_url = await blob_storage.backend.generate_presigned_url(
                    storage_key,
                    expires_in=PRESIGNED_URL_EXPIRY,
                )
                return {"presigned_url": presigned_url, "expires_in": PRESIGNED_URL_EXPIRY}
            except NotImplementedError:
                logger.warning("Pre-signed URLs not supported by current storage backend")
            except Exception as e:
                logger.warning(f"Failed to generate pre-signed URL: {e}")

        # Correct MIME type for PDFs if stored with wrong type
        if filename.lower().endswith(".pdf"):
            mime_type = "application/pdf"

        # inline disposition so browsers render PDFs natively
        return Response(
            content=content,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Content-Length": str(len(content)),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download document: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download document: {e}")


@router.get("/{doc_id}/presigned-url")
async def get_presigned_url(
    doc_id: str,
    expires_in: int = Query(3600, ge=60, le=86400, description="URL expiry in seconds"),
    facade=Depends(get_graph_kb_facade),
):
    """Get a pre-signed URL for direct S3 download.

    Useful for large files to avoid proxying through the API.
    Returns URL that expires after the specified time (default 1 hour, max 24 hours).
    """
    try:
        # Get document metadata from ChromaDB
        vector_store = facade.vector_store
        if not vector_store:
            raise HTTPException(status_code=503, detail="ChromaDB not available")

        result = vector_store.get(doc_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        meta = result.metadata or {}
        storage_key = meta.get("storage_key")

        if not storage_key:
            raise HTTPException(
                status_code=400,
                detail="Document not stored in S3 (no storage_key)",
            )

        # Generate pre-signed URL
        blob_storage: BlobStorage = BlobStorage.from_env()

        try:
            presigned_url = await blob_storage.backend.generate_presigned_url(
                storage_key,
                expires_in=expires_in,
            )
        except NotImplementedError:
            raise HTTPException(
                status_code=501,
                detail="Pre-signed URLs not supported by current storage backend",
            )

        return {
            "presigned_url": presigned_url,
            "expires_in": expires_in,
            "filename": meta.get("filename"),
            "mime_type": meta.get("mime_type"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate pre-signed URL: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate pre-signed URL: {e}")


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    delete_from_storage: bool = Query(False, description="Also delete from S3/blob storage"),
    facade=Depends(get_graph_kb_facade),
):
    """Delete a document.

    By default, only removes from ChromaDB index.
    Set delete_from_storage=true to also remove the file from S3/blob storage.
    """
    try:
        vector_store = _ensure_vector_store(facade)

        # Get metadata before deletion to check for storage_key
        result = vector_store.get(doc_id)
        storage_key = None
        if result and result.metadata:
            storage_key = result.metadata.get("storage_key")

        # Delete from ChromaDB
        vector_store.delete(doc_id)

        # Optionally delete from S3
        if delete_from_storage and storage_key:
            try:
                blob_storage: BlobStorage = BlobStorage.from_env()
                await blob_storage.backend.delete(storage_key)
                logger.info(f"Deleted document {doc_id} from both ChromaDB and storage")
            except Exception as e:
                logger.warning(f"Failed to delete from storage: {e}")
                # Already deleted from ChromaDB, don't fail the request

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.patch("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: str,
    update_data: DocumentUpdateRequest,
    facade=Depends(get_graph_kb_facade),
):
    """Update a document's metadata (e.g. category).

    Updates ChromaDB if the document is indexed there, and always updates
    the blob storage .meta.json so blob-only documents are also supported.
    """
    try:
        new_category = (update_data.category.strip() if update_data.category else None) or None

        # --- Update blob storage metadata (source of truth) ---
        blob_updated = False
        blob_filename: Optional[str] = None
        blob_parent: Optional[str] = None
        blob_created_at: Optional[str] = None
        try:
            bs = BlobStorage.from_env()
            blob_items = await bs.backend.list_with_metadata("documents/")
            blob_item = next(
                (item for item in blob_items if item["metadata"].get("doc_id") == doc_id),
                None,
            )
            if blob_item:
                blob_meta = dict(blob_item["metadata"])
                if new_category is not None:
                    blob_meta["category"] = new_category
                else:
                    blob_meta.pop("category", None)
                await bs.backend.write_metadata(blob_item["path"], blob_meta)
                blob_updated = True
                blob_filename = blob_meta.get("original_filename") or blob_meta.get("filename")
                blob_parent = blob_meta.get("parent") or None
                blob_created_at = blob_meta.get("created_at")
        except Exception as e:
            logger.warning(f"Failed to update blob metadata for {doc_id}: {e}")

        # --- Update ChromaDB if indexed ---
        vector_store = _ensure_vector_store(facade)
        result = vector_store.get(doc_id)
        if result:
            meta = dict(result.metadata or {})
            if new_category is not None:
                meta["category"] = new_category
            else:
                meta.pop("category", None)
            vector_store.collection.update(ids=[doc_id], metadatas=[meta])
            filename = meta.get("filename") or meta.get("file_path") or blob_filename or doc_id
            return DocumentResponse(
                id=doc_id,
                filename=filename,
                parent=meta.get("parent") or meta.get("repo_id") or blob_parent,
                category=meta.get("category"),
                content=None,
                metadata=meta,
                created_at=meta.get("created_at") or blob_created_at or datetime.now(timezone.utc).isoformat(),
            )

        if blob_updated:
            return DocumentResponse(
                id=doc_id,
                filename=blob_filename or doc_id,
                parent=blob_parent,
                category=new_category,
                content=None,
                metadata={"doc_id": doc_id, "category": new_category},
                created_at=blob_created_at or datetime.now(timezone.utc).isoformat(),
                indexed_for_search=False,
            )

        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update document: {e}")
