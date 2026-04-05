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
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
        vector_store = _ensure_vector_store(facade)

        # Get all documents with metadata
        results = vector_store.collection.get(include=["metadatas"])

        metadatas = results.get("metadatas", [])

        # Extract distinct values
        parents = set()
        categories = set()

        for meta in metadatas:
            if meta:
                # Use parent if available, otherwise repo_id (for repo chunks)
                parent = meta.get("parent") or meta.get("repo_id")
                if parent:
                    parents.add(parent)
                if meta.get("category"):
                    categories.add(meta["category"])

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

    By default, returns only user-uploaded documents (those stored in S3/blob storage).
    Set user_uploads_only=false to include repo code chunks.
    """
    try:
        vector_store = _ensure_vector_store(facade)

        # Build chromadb where filter
        where_clauses = []
        if parent:
            where_clauses.append({"parent": parent})
        if category:
            where_clauses.append({"category": category})

        # Note: We filter for user_uploads_only in Python after retrieval
        # because ChromaDB doesn't support $ne operator in where clauses

        where = None
        if len(where_clauses) == 1:
            where = where_clauses[0]
        elif len(where_clauses) > 1:
            where = {"$and": where_clauses}

        # Query the collection directly for filtering support
        kwargs = {"include": ["metadatas", "documents"]}
        if where:
            kwargs["where"] = where

        results = vector_store.collection.get(**kwargs)

        all_ids = results.get("ids", [])
        all_metadatas = results.get("metadatas", [])
        all_documents = results.get("documents", [])

        # Filter for user uploads only (documents with storage_key OR filename metadata)
        # ChromaDB doesn't support $ne, so we filter in Python
        # User uploads have: storage_key (new), filename (all), mime_type
        # Repo chunks have: repo_id, file_path, symbol_name
        if user_uploads_only:
            user_upload_indices = []
            for i, doc_id in enumerate(all_ids):
                meta = all_metadatas[i] if all_metadatas else {}
                # User uploads have storage_key (new uploads) OR filename without repo_id (older uploads)
                has_storage_key = meta and meta.get("storage_key")
                has_filename_no_repo = meta and meta.get("filename") and not meta.get("repo_id")
                if has_storage_key or has_filename_no_repo:
                    user_upload_indices.append(i)

            logger.info(f"Filter: found {len(user_upload_indices)} user uploads out of {len(all_ids)} total documents")
            all_ids = [all_ids[i] for i in user_upload_indices]
            all_metadatas = [all_metadatas[i] for i in user_upload_indices]
            all_documents = [all_documents[i] for i in user_upload_indices] if all_documents else []

        total = len(all_ids)

        # Apply pagination
        page_ids = all_ids[offset : offset + limit]
        page_metadatas = all_metadatas[offset : offset + limit]
        page_documents = all_documents[offset : offset + limit] if all_documents else [None] * len(page_ids)

        documents = []
        for i, doc_id in enumerate(page_ids):
            meta = page_metadatas[i] if page_metadatas else {}
            content = page_documents[i] if page_documents else None
            # Use filename if available, otherwise file_path (for repo chunks), otherwise doc_id
            filename = meta.get("filename") or meta.get("file_path") or doc_id
            documents.append(
                DocumentResponse(
                    id=doc_id,
                    filename=filename,
                    parent=meta.get("parent") or meta.get("repo_id"),
                    category=meta.get("category"),
                    content=content,
                    metadata=meta,
                    created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
                )
            )

        return DocumentListResponse(
            documents=documents,
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
    """Get a single document by ID with its content and metadata."""
    try:
        vector_store = _ensure_vector_store(facade)

        result = vector_store.get(doc_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        meta = result.metadata or {}
        # Use filename if available, otherwise file_path (for repo chunks), otherwise chunk_id
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
                    "parent": parent,
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
                # Binary file - can't index in ChromaDB
                logger.info(f"Binary file {filename} stored in S3 only (not indexed)")
                metadata["indexed_for_search"] = False
                return DocumentResponse(
                    id=doc_id,
                    filename=filename,
                    parent=parent,
                    category=None,
                    content=None,  # Binary content not returned
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
    """Download a document from S3/blob storage.

    By default, returns the file content directly.
    Set use_presigned=true to get a pre-signed URL for direct S3 access.
    """
    try:
        # Get document metadata from ChromaDB
        vector_store = facade.vector_store
        if vector_store:
            result = vector_store.get(doc_id)
            if not result:
                raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
            meta = result.metadata or {}
        else:
            # If ChromaDB unavailable, we can't look up by doc_id
            raise HTTPException(
                status_code=503,
                detail="Document lookup unavailable - ChromaDB not reachable",
            )

        storage_key = meta.get("storage_key")
        if not storage_key:
            # Document not stored in S3, return content from ChromaDB if available
            content = result.content if result else None
            if not content:
                raise HTTPException(
                    status_code=404,
                    detail="Document content not available (not stored in S3)",
                )
            filename = meta.get("filename", doc_id)
            return Response(
                content=content.encode("utf-8"),
                media_type=meta.get("mime_type", "text/plain"),
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                },
            )

        # Retrieve from S3/blob storage
        blob_storage: BlobStorage = BlobStorage.from_env()
        result_binary = await blob_storage.backend.retrieve_binary(storage_key)

        if not result_binary:
            raise HTTPException(status_code=404, detail="Document file not found in storage")

        content, _ = result_binary
        filename = meta.get("filename", doc_id)
        mime_type = meta.get("mime_type", "application/octet-stream")

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
                # Fall through to direct download
            except Exception as e:
                logger.warning(f"Failed to generate pre-signed URL: {e}")
                # Fall through to direct download

        # Return file content
        return Response(
            content=content,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
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
    """Update a document's metadata (e.g. category)."""
    try:
        vector_store = _ensure_vector_store(facade)

        result = vector_store.get(doc_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        meta = result.metadata or {}

        # update fields...
        if update_data.category is not None:
            if update_data.category.strip() == "":
                meta.pop("category", None)
            else:
                meta["category"] = update_data.category.strip()

        vector_store.collection.update(ids=[doc_id], metadatas=[meta])

        filename = meta.get("filename") or meta.get("file_path") or result.chunk_id
        return DocumentResponse(
            id=result.chunk_id,
            filename=filename,
            parent=meta.get("parent") or meta.get("repo_id"),
            category=meta.get("category"),
            content=None,  # Do not return content payload on patches to save bandwidth
            metadata=meta,
            created_at=meta.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update document: {e}")
