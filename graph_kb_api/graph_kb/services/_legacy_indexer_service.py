"""Indexer Service V2 for two-pass repository ingestion pipeline.

This module provides the IndexerServiceV2 class that implements a two-pass
indexing architecture for cross-file relationship resolution:

Pass 1 (Parallel): Process files in parallel, extract symbols, create nodes,
                   collect relationships without creating edges
Pass 2 (Sequential): Build global symbol registry, resolve cross-file references,
                     create relationship edges
"""

import gc
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from graph_kb_api.utils.enhanced_logger import EnhancedLogger

from ..config import DualWriteConfig
from ..models.base import (
    Chunk,
    GraphEdge,
    GraphNode,
    IngestionConfig,
    Relationship,
    RepoMetadata,
    SymbolInfo,
)
from ..models.enums import (
    GraphEdgeType,
    GraphNodeType,
    IndexingPhase,
    Language,
    RelationshipType,
    RepoStatus,
)
from ..models.exceptions import (
    EmbeddingDimensionError,
    IndexerServiceV2Error,
)
from ..models.ingestion import FileIndexResult, IndexingProgress, ResolutionStats
from ..parsing.language_parser import TreeSitterLanguageParser
from ..parsing.module_resolver import ModuleResolver
from ..parsing.symbol_extractor import SymbolExtractorV2
from ..parsing.symbol_registry import GlobalSymbolRegistry
from ..processing.chunker import SemanticChunker
from ..processing.embedding_generator import EmbeddingGenerator
from ..repositories.file_discovery import FileSystemDiscovery
from ..storage import MetadataStore
from ..storage.graph_store import Neo4jGraphStore
from ..storage.vector_store import ChromaVectorStore

logger = EnhancedLogger(__name__)

ProgressCallback = Callable[[IndexingProgress], None]


class IndexerService:
    """Two-pass indexer service for cross-file relationship resolution.

    This class implements a two-pass indexing architecture:

    Pass 1 (Parallel):
        - Process files in parallel using ThreadPoolExecutor
        - Extract symbols and create symbol nodes
        - Collect relationships without creating edges
        - Return FileIndexResult for each file

    Pass 2 (Sequential):
        - Build GlobalSymbolRegistry from all FileIndexResults
        - Build ModuleResolver with complete file set
        - Resolve cross-file relationships
        - Create relationship edges in the graph
    """

    def __init__(
        self,
        graph_store: Neo4jGraphStore,
        vector_store: ChromaVectorStore,
        metadata_store: MetadataStore,
        embedding_generator: EmbeddingGenerator,
        ingestion_config: Optional[IngestionConfig] = None,
        dual_write_config: Optional[DualWriteConfig] = None,
    ):
        """Initialize the IndexerServiceV2.

        Args:
            graph_store: Neo4j graph store instance.
            vector_store: ChromaDB vector store instance.
            metadata_store: Metadata store instance.
            embedding_generator: Embedding generator instance.
            ingestion_config: Optional ingestion configuration.
            dual_write_config: Optional dual-write configuration.
        """
        self._graph_store = graph_store
        self._vector_store = vector_store
        self._metadata_store = metadata_store
        self._embedding_generator = embedding_generator
        self._config = ingestion_config or IngestionConfig()
        self._dual_write_config = dual_write_config or DualWriteConfig()

        # Initialize pipeline components
        self._file_discovery = FileSystemDiscovery(self._config)
        self._language_parser = TreeSitterLanguageParser()
        self._symbol_extractor = SymbolExtractorV2(self._language_parser)
        self._chunker = SemanticChunker()

        # Pause control flag
        self._pause_requested = False

        # Flag to track if indexes have been ensured
        self._indexes_ensured = False

    def request_pause(self) -> None:
        """Request the indexing process to pause at the next checkpoint."""
        self._pause_requested = True
        logger.info("Pause requested for indexing process")

    def clear_pause(self) -> None:
        """Clear the pause request flag."""
        self._pause_requested = False

    def is_pause_requested(self) -> bool:
        """Check if a pause has been requested."""
        return self._pause_requested

    def _ensure_indexes(self) -> None:
        """Ensure Neo4j indexes are created (lazy initialization)."""
        if not self._indexes_ensured:
            self._graph_store.ensure_indexes()
            self._indexes_ensured = True

    def index_repo(
        self,
        repo_id: str,
        repo_path: str,
        git_url: str,
        branch: str,
        commit_sha: str,
        progress_callback: Optional[ProgressCallback] = None,
        resume: bool = False,
    ) -> IndexingProgress:
        """Run two-pass indexing pipeline for a repository.

        This method implements the two-pass architecture:

        Pass 1 (Parallel):
            1. Discover eligible files
            2. Process files in parallel with _index_file_collect
            3. Collect FileIndexResults with symbols and deferred relationships

        Pass 2 (Sequential):
            1. Build GlobalSymbolRegistry from all results
            2. Build ModuleResolver with file set
            3. Resolve cross-file relationships with _resolve_all_relationships
            4. Create relationship edges

        Then continues with embedding generation and storage.

        Args:
            repo_id: Unique repository identifier.
            repo_path: Local path to the repository.
            git_url: Git URL of the repository.
            branch: Branch being indexed.
            commit_sha: Current commit SHA.
            progress_callback: Optional callback for progress updates.
            resume: If True, skip files that have already been indexed.

        Returns:
            IndexingProgress with final status and statistics.
        """
        logger.info(
            f"Starting two-pass indexing for repo {repo_id} at {repo_path} (resume={resume})"
        )

        logger.info("Starting index_repo", data={"repo_id": repo_id, "resume": resume})

        progress = IndexingProgress(
            repo_id=repo_id,
            phase=IndexingPhase.INITIALIZING,
            message="Initializing two-pass indexing pipeline...",
        )

        try:
            # Ensure Neo4j indexes are created (lazy initialization)
            self._ensure_indexes()
            # Ensure repo metadata exists and update status
            # NOTE: must happen BEFORE _notify_progress so the FK on
            # indexing_progress.repo_id is satisfied.
            self._ensure_repo_metadata(repo_id, git_url, branch, repo_path)
            self._metadata_store.update_status(repo_id, RepoStatus.INDEXING)
            self._metadata_store.update_indexing_phase(repo_id, "indexing")

            self._notify_progress(progress, progress_callback)

            # Create repo node in graph
            self._create_repo_node(repo_id, git_url, branch)

            # Check if resuming from embedding phase (pending chunks exist)
            pending_chunks_count = (
                self._metadata_store.get_pending_chunks_count(repo_id) if resume else 0
            )

            # When not resuming, clear stale pending chunks from any previous run
            if not resume:
                try:
                    self._metadata_store.clear_pending_chunks(repo_id)
                except Exception as e:
                    logger.warning(f"Failed to clear stale pending chunks: {e}")
            logger.debug(
                "Checking for pending chunks",
                data={
                    "repo_id": repo_id,
                    "resume": resume,
                    "pending_chunks_count": pending_chunks_count,
                },
            )

            if resume and pending_chunks_count > 0:
                # Resume from embedding phase - skip Pass 1 and Pass 2
                logger.info(
                    "Resuming from embedding phase - loading pending chunks",
                    data={
                        "repo_id": repo_id,
                        "pending_chunks_count": pending_chunks_count,
                    },
                )

                # Load pending chunks and symbol_chunk_links
                all_chunks_with_file, all_symbol_chunk_links = (
                    self._metadata_store.get_pending_chunks(repo_id)
                )

                logger.debug(
                    "Loaded pending chunks",
                    data={
                        "repo_id": repo_id,
                        "chunks_count": len(all_chunks_with_file),
                        "symbol_chunk_links_count": len(all_symbol_chunk_links),
                    },
                )

                if not all_chunks_with_file:
                    logger.warning(
                        f"No pending chunks found for repo {repo_id} despite count={pending_chunks_count}"
                    )
                    progress.phase = IndexingPhase.ERROR
                    progress.message = "No pending chunks found to resume embedding"
                    self._notify_progress(progress, progress_callback)
                    return progress

                # Convert file_path to file_node_id format
                # Note: save_pending_chunks stores file_node_id as file_path when called from IndexerServiceV2,
                # so the stored value is already in file_node_id format (repo_id:file_path)
                chunks_with_file_node_id = []
                for chunk, file_path_or_node_id in all_chunks_with_file:
                    # Check if it's already in file_node_id format (starts with repo_id:)
                    # This handles the case where save_pending_chunks stored file_node_id as file_path
                    if file_path_or_node_id.startswith(f"{repo_id}:"):
                        file_node_id = file_path_or_node_id
                    else:
                        # It's just a file_path, convert to file_node_id format
                        file_node_id = f"{repo_id}:{file_path_or_node_id}"
                    chunks_with_file_node_id.append((chunk, file_node_id))

                # Get checkpoint stats to populate progress with correct counts
                checkpoint_stats = self._metadata_store.get_checkpoint_progress(repo_id)

                # Calculate processed files correctly from database state
                # processed_files should include completed + failed + skipped files
                # since they've all been "processed" (attempted)
                completed_files = checkpoint_stats.get("completed", 0)
                failed_files = checkpoint_stats.get("failed", 0)
                skipped_files = checkpoint_stats.get("skipped", 0)
                processed_files = completed_files + failed_files + skipped_files

                # Update progress
                progress.phase = IndexingPhase.GENERATING_EMBEDDINGS
                progress.total_chunks = len(chunks_with_file_node_id)
                progress.total_chunks_to_embed = len(chunks_with_file_node_id)
                progress.processed_chunks = 0
                progress.processed_files = processed_files
                progress.total_files = checkpoint_stats.get("total", 0)
                progress.total_symbols = checkpoint_stats.get("total_symbols", 0)
                progress.completed_files = completed_files
                progress.failed_files = failed_files
                progress.skipped_files = skipped_files
                progress.message = f"Resuming: Generating embeddings for {len(chunks_with_file_node_id)} chunks..."

                logger.debug(
                    "Setting progress statistics for resume",
                    data={
                        "repo_id": repo_id,
                        "total_chunks": progress.total_chunks,
                        "total_symbols": progress.total_symbols,
                        "processed_files": progress.processed_files,
                        "total_files": progress.total_files,
                        "checkpoint_stats": checkpoint_stats,
                    },
                )

                logger.debug(
                    "Setting progress statistics for resume",
                    data={
                        "repo_id": repo_id,
                        "total_chunks": progress.total_chunks,
                        "total_symbols": progress.total_symbols,
                        "processed_files": progress.processed_files,
                        "total_files": progress.total_files,
                        "checkpoint_stats": checkpoint_stats,
                    },
                )

                # Debug: Log detailed checkpoint stats to understand the issue
                logger.info(
                    f"Resume checkpoint stats for {repo_id}: "
                    f"total={checkpoint_stats.get('total', 0)}, "
                    f"completed={checkpoint_stats.get('completed', 0)}, "
                    f"failed={checkpoint_stats.get('failed', 0)}, "
                    f"pending={checkpoint_stats.get('pending', 0)}, "
                    f"processing={checkpoint_stats.get('processing', 0)}, "
                    f"skipped={checkpoint_stats.get('skipped', 0)}"
                )

                # Get detailed debug info to understand the database state
                debug_info = self._metadata_store.get_file_status_debug(repo_id)
                logger.info(
                    f"File status debug for {repo_id}: {debug_info['status_counts']}"
                )
                logger.debug(
                    f"Sample files for {repo_id}: {debug_info['sample_files'][:5]}"
                )

                self._notify_progress(progress, progress_callback)

                # Generate embeddings and store chunks
                embedding_completed = self._store_chunks_with_embeddings(
                    chunks_with_file_node_id,
                    all_symbol_chunk_links,
                    progress=progress,
                    progress_callback=progress_callback,
                )

                # Only finalize if embedding completed successfully
                if not embedding_completed:
                    # Embedding was paused (e.g., due to OOM)
                    # Don't clear pending chunks or mark as completed
                    progress.phase = IndexingPhase.PAUSED
                    progress.message = (
                        f"Paused: {progress.processed_chunks}/{progress.total_chunks_to_embed} chunks embedded. "
                        f"Use --resume to continue."
                    )
                    self._metadata_store.update_status(repo_id, RepoStatus.PAUSED)
                    self._metadata_store.update_indexing_phase(repo_id, "paused")
                    logger.info(
                        f"Embedding paused for repo {repo_id}: {progress.message}"
                    )
                    self._notify_progress(progress, progress_callback)
                    return progress

                # Clear pending chunks after successful embedding
                self._metadata_store.clear_pending_chunks(repo_id)

                # Finalize
                progress.phase = IndexingPhase.FINALIZING
                progress.message = "Finalizing indexing..."
                self._notify_progress(progress, progress_callback)

                self._metadata_store.update_status(repo_id, RepoStatus.READY)
                self._metadata_store.update_indexed_commit(repo_id, commit_sha)
                self._metadata_store.update_indexing_phase(repo_id, "completed")

                progress.phase = IndexingPhase.COMPLETED
                progress.message = (
                    f"Completed: Resumed embedding for {len(chunks_with_file_node_id)} chunks, "
                    f"{progress.total_symbols} symbols, {progress.processed_files} files indexed"
                )
                logger.info(
                    f"Completed resumed embedding for repo {repo_id}: {progress.message}"
                )

                logger.info(
                    "Resume embedding completed",
                    data={
                        "repo_id": repo_id,
                        "total_chunks": progress.total_chunks,
                        "total_symbols": progress.total_symbols,
                        "processed_files": progress.processed_files,
                        "message": progress.message,
                    },
                )

                self._notify_progress(progress, progress_callback)

                try:
                    self._metadata_store.delete_indexing_progress(repo_id)
                except Exception as e:
                    logger.warning(f"Failed to clean up indexing progress: {e}")

                # Clear embedding progress on successful completion
                try:
                    self._metadata_store.clear_embedding_progress(repo_id)
                except Exception as e:
                    logger.warning(f"Failed to clean up embedding progress: {e}")

                return progress

            # Discover files
            progress.phase = IndexingPhase.DISCOVERING_FILES
            progress.message = "Discovering files..."
            self._notify_progress(progress, progress_callback)

            all_files = self._file_discovery.discover_files(repo_path)
            progress.total_files = len(all_files)

            # Check for previously processed files if resuming
            files_to_process = all_files
            if resume:
                logger.info(
                    "Resume=True but no pending chunks, checking remaining files"
                )
                files_to_process = self._metadata_store.get_remaining_files(
                    repo_id, all_files
                )
                progress.skipped_files = len(all_files) - len(files_to_process)
                progress.remaining_files = len(files_to_process)

                checkpoint_stats = self._metadata_store.get_checkpoint_progress(repo_id)
                logger.debug(f"Checkpoint stats: {checkpoint_stats}")
                progress.completed_files = checkpoint_stats.get("completed", 0)
                progress.failed_files = checkpoint_stats.get("failed", 0)
                # Load existing chunk/symbol counts from checkpoint for accurate statistics
                progress.total_chunks = checkpoint_stats.get("total_chunks", 0)
                progress.total_symbols = checkpoint_stats.get("total_symbols", 0)
                logger.debug(
                    f"Loaded from checkpoint: total_chunks={progress.total_chunks}, total_symbols={progress.total_symbols}"
                )

                progress.message = (
                    f"Discovered {len(all_files)} files, "
                    f"skipping {progress.skipped_files} already indexed, "
                    f"{len(files_to_process)} remaining"
                )

                logger.debug(
                    f"Resume path: total_files={len(all_files)}, files_to_process={len(files_to_process)}, skipped={progress.skipped_files}"
                )

                # Handle edge case: all files indexed but no pending chunks
                # This means Pass 1 & 2 completed but embedding may have failed
                if len(files_to_process) == 0:
                    # Check embedding progress first
                    embedding_progress = self._metadata_store.get_embedding_progress(
                        repo_id
                    )
                    if embedding_progress:
                        logger.debug(f"Embedding progress found: {embedding_progress}")
                        emb_status = embedding_progress.get("status")
                        emb_total = embedding_progress.get("total_chunks", 0)
                        emb_done = embedding_progress.get("embedded_chunks", 0)
                        emb_failed = embedding_progress.get("failed_chunks", 0)

                        if emb_status == "completed":
                            # Embedding already completed
                            progress.phase = IndexingPhase.COMPLETED
                            progress.total_chunks = emb_total
                            progress.processed_chunks = emb_done
                            progress.message = (
                                f"Indexing already complete: {emb_done} chunks embedded, "
                                f"{emb_failed} failed"
                            )
                            logger.info(
                                f"Resume detected completed embedding for repo {repo_id}"
                            )
                            self._metadata_store.update_status(
                                repo_id, RepoStatus.READY
                            )
                            self._metadata_store.update_indexed_commit(
                                repo_id, commit_sha
                            )
                            self._notify_progress(progress, progress_callback)
                            return progress
                        elif emb_status in ("in_progress", "paused") and emb_done > 0:
                            # Embedding was interrupted - need to resume
                            # The embedding progress will be used by _store_chunks_with_subprocess_embeddings
                            # to skip already-processed chunks
                            logger.debug(
                                f"Embedding in progress/paused: {emb_done}/{emb_total} done, will resume"
                            )

                    # Check if symbols exist in the graph store
                    try:
                        graph_stats = self._graph_store.get_repo_stats(repo_id)
                        symbol_count_in_graph = (
                            graph_stats.get("symbol_count", 0) if graph_stats else 0
                        )
                        file_count_in_graph = (
                            graph_stats.get("file_count", 0) if graph_stats else 0
                        )
                        logger.debug(
                            f"All files indexed, no pending chunks. Symbols in graph: {symbol_count_in_graph}, Files: {file_count_in_graph}, total_chunks from checkpoint: {progress.total_chunks}"
                        )

                        # Check if embeddings exist in vector store
                        vector_count = 0
                        try:
                            vector_count = self._vector_store.count(repo_id)
                            logger.debug(f"Chunks in vector store: {vector_count}")
                        except Exception as ve:
                            logger.warning(f"Failed to count vectors: {ve}")

                        if (
                            vector_count > 0
                            and progress.total_chunks > 0
                            and vector_count >= progress.total_chunks * 0.9
                        ):
                            # Embeddings exist and count is close to expected, indexing is complete
                            progress.total_symbols = symbol_count_in_graph
                            progress.processed_files = file_count_in_graph
                            progress.phase = IndexingPhase.COMPLETED
                            progress.message = (
                                f"Indexing already complete: {progress.processed_files} files, "
                                f"{progress.total_chunks} chunks, {progress.total_symbols} symbols"
                            )
                            logger.info(
                                f"Resume detected completed indexing for repo {repo_id}"
                            )
                            self._metadata_store.update_status(
                                repo_id, RepoStatus.READY
                            )
                            self._metadata_store.update_indexed_commit(
                                repo_id, commit_sha
                            )
                            self._notify_progress(progress, progress_callback)
                            return progress
                        elif symbol_count_in_graph > 0 or file_count_in_graph > 0:
                            # Chunks were created but embeddings are missing
                            # Need to regenerate chunks from indexed files and run embedding
                            logger.info(
                                f"Chunks exist ({progress.total_chunks}) but embeddings missing ({vector_count}). Regenerating chunks for embedding..."
                            )

                            progress.phase = IndexingPhase.GENERATING_EMBEDDINGS
                            progress.message = f"Regenerating chunks from {file_count_in_graph} indexed files for embedding..."
                            self._notify_progress(progress, progress_callback)

                            # Regenerate chunks from all indexed files
                            all_chunks, all_symbol_chunk_links = (
                                self._regenerate_chunks_from_indexed_files(
                                    repo_id=repo_id,
                                    repo_path=repo_path,
                                    all_files=all_files,
                                    commit_sha=commit_sha,
                                    progress=progress,
                                    progress_callback=progress_callback,
                                )
                            )

                            if all_chunks:
                                logger.debug(
                                    f"Regenerated {len(all_chunks)} chunks for embedding"
                                )
                                progress.total_chunks = len(all_chunks)
                                progress.total_chunks_to_embed = len(all_chunks)
                                progress.message = f"Generating embeddings for {len(all_chunks)} chunks..."
                                self._notify_progress(progress, progress_callback)

                                # Generate embeddings and store chunks
                                embedding_completed = (
                                    self._store_chunks_with_embeddings(
                                        all_chunks,
                                        all_symbol_chunk_links,
                                        progress=progress,
                                        progress_callback=progress_callback,
                                    )
                                )

                                # Only finalize if embedding completed successfully
                                if not embedding_completed:
                                    # Embedding was paused (e.g., due to OOM)
                                    progress.phase = IndexingPhase.PAUSED
                                    progress.message = (
                                        f"Paused: {progress.processed_chunks}/{progress.total_chunks_to_embed} chunks embedded. "
                                        f"Use --resume to continue."
                                    )
                                    self._metadata_store.update_status(
                                        repo_id, RepoStatus.PAUSED
                                    )
                                    self._metadata_store.update_indexing_phase(
                                        repo_id, "paused"
                                    )
                                    logger.info(
                                        f"Embedding paused for repo {repo_id}: {progress.message}"
                                    )
                                    self._notify_progress(progress, progress_callback)
                                    return progress

                                # Finalize
                                progress.phase = IndexingPhase.FINALIZING
                                progress.message = "Finalizing indexing..."
                                self._notify_progress(progress, progress_callback)

                                self._metadata_store.update_status(
                                    repo_id, RepoStatus.READY
                                )
                                self._metadata_store.update_indexed_commit(
                                    repo_id, commit_sha
                                )
                                self._metadata_store.update_indexing_phase(
                                    repo_id, "completed"
                                )

                                # Clear embedding progress on successful completion
                                try:
                                    self._metadata_store.clear_embedding_progress(
                                        repo_id
                                    )
                                except Exception as e:
                                    logger.warning(
                                        f"Failed to clean up embedding progress: {e}"
                                    )

                                progress.phase = IndexingPhase.COMPLETED
                                progress.message = (
                                    f"Completed: {progress.processed_files} files, "
                                    f"{progress.total_chunks} chunks embedded, {progress.total_symbols} symbols"
                                )
                                logger.info(
                                    f"Completed resumed embedding for repo {repo_id}: {progress.message}"
                                )
                                self._notify_progress(progress, progress_callback)
                                return progress
                            else:
                                logger.warning(
                                    f"Failed to regenerate chunks for repo {repo_id}"
                                )
                                # Return error since we can't proceed without chunks
                                progress.phase = IndexingPhase.ERROR
                                progress.message = (
                                    "Failed to regenerate chunks from indexed files"
                                )
                                self._notify_progress(progress, progress_callback)
                                return progress
                        else:
                            # No chunks and no symbols - something is wrong
                            logger.warning(
                                f"No chunks or symbols found for repo {repo_id} despite files being indexed"
                            )
                            # Return error since there's nothing to embed
                            progress.phase = IndexingPhase.ERROR
                            progress.message = "No symbols or files found in graph despite files being indexed"
                            self._notify_progress(progress, progress_callback)
                            return progress
                    except Exception as e:
                        logger.warning(
                            f"Failed to check graph stats during resume: {e}"
                        )
                        # Continue to normal flow as fallback

                logger.debug(
                    "Resume: files to process (no pending chunks)",
                    data={
                        "repo_id": repo_id,
                        "total_files": len(all_files),
                        "files_to_process": len(files_to_process),
                        "skipped_files": progress.skipped_files,
                        "checkpoint_stats": checkpoint_stats,
                    },
                )
            else:
                self._metadata_store.clear_file_index(repo_id)
                progress.remaining_files = len(all_files)
                progress.message = f"Discovered {len(all_files)} files for indexing"

            logger.info(progress.message)
            self._notify_progress(progress, progress_callback)

            # Create directory nodes
            progress.message = "Creating directory structure..."
            self._notify_progress(progress, progress_callback)
            self._create_directory_nodes(repo_id, all_files)

            # ============================================================
            # PASS 1: Parallel file processing with _index_file_collect
            # ============================================================
            progress.phase = IndexingPhase.INDEXING_FILES
            progress.message = "Pass 1: Processing files in parallel..."
            self._notify_progress(progress, progress_callback)

            all_results: List[FileIndexResult] = []
            all_chunks: List[Tuple[Chunk, str]] = []
            all_symbol_chunk_links: List[Tuple[str, str]] = []

            was_paused = False
            progress_lock = threading.Lock()
            results_lock = threading.Lock()
            processed_count = [0]

            max_workers = self._config.max_indexing_workers
            total_files = len(files_to_process)

            logger.info(
                f"Pass 1: Starting parallel indexing with {max_workers} workers for {total_files} files"
            )

            def process_file(file_path: str) -> Optional[FileIndexResult]:
                """Process a single file - thread-safe worker function."""
                if self._pause_requested:
                    return None

                full_path = Path(repo_path) / file_path

                try:
                    file_hash = self._compute_file_hash(str(full_path))
                except Exception as e:
                    error_msg = f"Failed to compute hash for {file_path}: {e}"
                    logger.warning(error_msg)
                    with progress_lock:
                        progress.errors.append(error_msg)
                        progress.failed_files += 1
                    self._metadata_store.mark_file_failed(
                        repo_id=repo_id,
                        file_path=file_path,
                        file_hash="",
                        error_message=str(e),
                    )
                    return None

                try:
                    result = self._index_file_collect(
                        repo_id=repo_id,
                        file_path=file_path,
                        repo_path=repo_path,
                        commit_sha=commit_sha,
                    )

                    self._metadata_store.mark_file_completed(
                        repo_id=repo_id,
                        file_path=file_path,
                        file_hash=file_hash,
                        chunk_count=len(result.chunks_with_file),
                        symbol_count=len(result.symbols),
                    )

                    return result

                except Exception as e:
                    error_msg = f"Failed to index file {file_path}: {e}"
                    logger.warning(error_msg)
                    with progress_lock:
                        progress.errors.append(error_msg)
                        progress.failed_files += 1
                    self._metadata_store.mark_file_failed(
                        repo_id=repo_id,
                        file_path=file_path,
                        file_hash=file_hash,
                        error_message=str(e),
                    )
                    return None

            # Execute parallel file processing
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(process_file, fp): fp for fp in files_to_process
                }

                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]

                    if self._pause_requested:
                        logger.info("Pause requested, cancelling remaining tasks...")
                        executor.shutdown(wait=False, cancel_futures=True)
                        was_paused = True
                        self._pause_requested = False
                        break

                    try:
                        result = future.result()

                        if result:
                            with results_lock:
                                all_results.append(result)
                                all_chunks.extend(result.chunks_with_file)
                                all_symbol_chunk_links.extend(result.symbol_chunk_links)

                            with progress_lock:
                                progress.total_chunks += len(result.chunks_with_file)
                                progress.total_symbols += len(result.symbols)
                                progress.total_relationships += len(
                                    result.relationships
                                )
                                progress.completed_files += 1
                                processed_count[0] += 1

                                progress.processed_files = (
                                    progress.skipped_files + processed_count[0]
                                )
                                progress.remaining_files = (
                                    total_files - processed_count[0]
                                )
                                progress.current_file = file_path
                                progress.message = (
                                    f"Pass 1: Indexed {processed_count[0]}/{total_files} files "
                                    f"(completed: {progress.completed_files}, failed: {progress.failed_files})"
                                )
                        else:
                            with progress_lock:
                                processed_count[0] += 1
                                progress.remaining_files = (
                                    total_files - processed_count[0]
                                )

                        self._notify_progress(progress, progress_callback)

                    except Exception as e:
                        logger.error(f"Unexpected error processing {file_path}: {e}")
                        with progress_lock:
                            progress.errors.append(
                                f"Unexpected error for {file_path}: {e}"
                            )
                            processed_count[0] += 1

            logger.info(
                f"Pass 1 complete: {progress.completed_files} succeeded, {progress.failed_files} failed"
            )

            logger.info(
                "Pass 1 complete",
                data={
                    "repo_id": repo_id,
                    "total_files": total_files,
                    "all_results_count": len(all_results),
                    "all_chunks_count": len(all_chunks),
                    "all_symbol_chunk_links_count": len(all_symbol_chunk_links),
                    "completed_files": progress.completed_files,
                    "failed_files": progress.failed_files,
                },
            )

            if was_paused:
                self._metadata_store.update_status(repo_id, RepoStatus.PAUSED)
                progress.phase = IndexingPhase.PAUSED
                progress.message = (
                    f"Paused: {progress.completed_files} files indexed, "
                    f"{progress.remaining_files} remaining. Use --resume to continue."
                )
                logger.info(f"Paused indexing repo {repo_id}: {progress.message}")
                self._notify_progress(progress, progress_callback)
                return progress

            # ============================================================
            # PASS 2: Sequential relationship resolution
            # ============================================================
            progress.phase = IndexingPhase.RESOLVING_RELATIONSHIPS
            progress.total_files_to_resolve = len(all_results)
            progress.resolved_files = 0
            progress.message = "Pass 2: Resolving cross-file relationships..."
            self._notify_progress(progress, progress_callback)

            # Build GlobalSymbolRegistry from all results
            registry = GlobalSymbolRegistry()
            file_set: Set[str] = set()

            for result in all_results:
                file_set.add(result.file_path)
                for symbol in result.symbols:
                    node_id = result.symbol_node_ids.get(symbol.symbol_id)
                    if node_id:
                        registry.register_symbol(symbol, node_id)

            # Build ModuleResolver
            module_resolver = ModuleResolver(repo_path, file_set)

            # Resolve all relationships
            resolution_stats = self._resolve_all_relationships(
                repo_id=repo_id,
                all_results=all_results,
                registry=registry,
                module_resolver=module_resolver,
                progress=progress,
                progress_callback=progress_callback,
            )

            progress.resolved_relationships = resolution_stats.created
            progress.external_relationships = resolution_stats.external
            progress.unresolved_relationships = resolution_stats.unresolved

            logger.info(
                f"Pass 2 complete: {resolution_stats.created} edges created, "
                f"{resolution_stats.external} external, {resolution_stats.unresolved} unresolved"
            )

            # Deduplicate chunks
            seen_chunk_ids = set()
            unique_chunks = []
            for chunk_with_file in all_chunks:
                chunk = chunk_with_file[0]
                if chunk.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk.chunk_id)
                    unique_chunks.append(chunk_with_file)

            if len(unique_chunks) < len(all_chunks):
                logger.info(
                    f"Deduplicated {len(all_chunks) - len(unique_chunks)} duplicate chunks"
                )
                all_chunks = unique_chunks

            # Save chunks to checkpoint
            progress.message = f"Saving {len(all_chunks)} chunks to checkpoint..."
            self._notify_progress(progress, progress_callback)

            self._metadata_store.save_pending_chunks(
                repo_id=repo_id,
                chunks_with_file=all_chunks,
                symbol_chunk_links=all_symbol_chunk_links,
            )

            self._metadata_store.update_indexing_phase(repo_id, "embedding")
            logger.info(
                f"Checkpoint saved: {len(all_chunks)} chunks ready for embedding"
            )

            # Generate embeddings and store chunks
            progress.phase = IndexingPhase.GENERATING_EMBEDDINGS
            progress.message = f"Generating embeddings for {len(all_chunks)} chunks..."
            self._notify_progress(progress, progress_callback)

            embedding_completed = self._store_chunks_with_embeddings(
                all_chunks,
                all_symbol_chunk_links,
                progress=progress,
                progress_callback=progress_callback,
            )

            # Only finalize if embedding completed successfully
            if not embedding_completed:
                # Embedding was paused (e.g., due to OOM)
                progress.phase = IndexingPhase.PAUSED
                progress.message = (
                    f"Paused: {progress.processed_chunks}/{progress.total_chunks_to_embed} chunks embedded. "
                    f"Use --resume to continue."
                )
                self._metadata_store.update_status(repo_id, RepoStatus.PAUSED)
                self._metadata_store.update_indexing_phase(repo_id, "paused")
                logger.info(f"Embedding paused for repo {repo_id}: {progress.message}")
                self._notify_progress(progress, progress_callback)
                return progress

            self._metadata_store.clear_pending_chunks(repo_id)

            # Finalize
            progress.phase = IndexingPhase.FINALIZING
            progress.processed_files = len(all_files)
            progress.remaining_files = 0
            progress.current_file = None
            progress.message = "Finalizing indexing..."
            self._notify_progress(progress, progress_callback)

            self._metadata_store.update_status(repo_id, RepoStatus.READY)
            self._metadata_store.update_indexed_commit(repo_id, commit_sha)
            self._metadata_store.update_indexing_phase(repo_id, "completed")

            progress.phase = IndexingPhase.COMPLETED
            progress.message = (
                f"Completed: {len(all_files)} total files, {progress.completed_files} indexed, "
                f"{progress.skipped_files} skipped, {progress.failed_files} failed, "
                f"{progress.total_chunks} chunks, {progress.total_symbols} symbols, "
                f"{progress.resolved_relationships} cross-file edges created"
            )
            logger.info(
                f"Completed two-pass indexing repo {repo_id}: {progress.message}"
            )
            self._notify_progress(progress, progress_callback)

            try:
                self._metadata_store.delete_indexing_progress(repo_id)
            except Exception as e:
                logger.warning(f"Failed to clean up indexing progress: {e}")

            # Clear embedding progress on successful completion
            try:
                self._metadata_store.clear_embedding_progress(repo_id)
            except Exception as e:
                logger.warning(f"Failed to clean up embedding progress: {e}")

            return progress

        except Exception as e:
            logger.error(f"Failed to index repo {repo_id}: {e}")
            progress.phase = IndexingPhase.ERROR
            progress.message = f"Indexing failed: {e}"
            progress.errors.append(str(e))
            self._notify_progress(progress, progress_callback)

            try:
                self._metadata_store.update_status(
                    repo_id, RepoStatus.ERROR, error_message=str(e)
                )
                self._metadata_store.update_indexing_phase(repo_id, "error")
                self._metadata_store.delete_indexing_progress(repo_id)
            except Exception:
                pass
            raise IndexerServiceV2Error(f"Indexing failed: {e}") from e

    def _index_file_collect(
        self,
        repo_id: str,
        file_path: str,
        repo_path: str,
        commit_sha: str,
    ) -> FileIndexResult:
        """Pass 1: Index a single file and collect data for Pass 2.

        Creates file and symbol nodes, collects relationships without creating
        edges. Returns a FileIndexResult containing all data needed for Pass 2
        relationship resolution.

        Args:
            repo_id: Repository identifier.
            file_path: Relative path to the file.
            repo_path: Absolute path to the repository root.
            commit_sha: Current commit SHA.

        Returns:
            FileIndexResult containing:
            - file_path and file_node_id
            - All extracted symbols
            - Symbol ID to node ID mapping
            - All relationships (resolved and unresolved)
            - Chunks and symbol-chunk links
        """
        full_path = Path(repo_path) / file_path

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        language = self._language_parser.detect_language(file_path, content)

        # Parse and extract symbols if supported
        symbols: List[SymbolInfo] = []
        relationships: List[Relationship] = []
        tree = None

        if self._language_parser.supports_language(language):
            parse_result = self._language_parser.parse(content, language)
            if parse_result and parse_result.success:
                tree = parse_result.tree
                symbols, relationships = self._symbol_extractor.extract_all(
                    tree, file_path, language, content
                )

        # Create file node in graph
        file_node_id = self._create_file_node(repo_id, file_path)

        # Create symbol nodes (but NOT relationship edges - deferred to Pass 2)
        symbol_node_ids: Dict[str, str] = {}
        for symbol in symbols:
            symbol_node_id = self._create_symbol_node(
                repo_id, file_path, symbol, file_node_id
            )
            symbol_node_ids[symbol.symbol_id] = symbol_node_id

        # Create chunks
        if tree and symbols:
            chunks = self._chunker.chunk_code(
                content=content,
                tree=tree,
                symbols=symbols,
                repo_id=repo_id,
                file_path=file_path,
                language=language,
                commit_sha=commit_sha,
            )
        else:
            chunks = self._chunker.chunk_text(
                content=content,
                repo_id=repo_id,
                file_path=file_path,
                commit_sha=commit_sha,
            )

        # Prepare chunk data with file association
        chunks_with_file = [(chunk, file_node_id) for chunk in chunks]

        # Build symbol-to-chunk links
        symbol_chunk_links: List[Tuple[str, str]] = []
        for chunk in chunks:
            chunk_node_id = f"{repo_id}:chunk:{chunk.chunk_id}"
            for symbol_name in chunk.symbols_defined:
                # Find the symbol by name to get its symbol_id
                for symbol in symbols:
                    if symbol.name == symbol_name:
                        if symbol.symbol_id in symbol_node_ids:
                            symbol_chunk_links.append(
                                (symbol_node_ids[symbol.symbol_id], chunk_node_id)
                            )
                        break

        logger.debug(
            f"Pass 1 indexed file {file_path}: {len(symbols)} symbols, "
            f"{len(chunks)} chunks, {len(relationships)} relationships (deferred)"
        )

        return FileIndexResult(
            file_path=file_path,
            file_node_id=file_node_id,
            language=language,
            symbols=symbols,
            symbol_node_ids=symbol_node_ids,
            relationships=relationships,
            chunks_with_file=chunks_with_file,
            symbol_chunk_links=symbol_chunk_links,
        )

    def _resolve_all_relationships(
        self,
        repo_id: str,
        all_results: List[FileIndexResult],
        registry: GlobalSymbolRegistry,
        module_resolver: ModuleResolver,
        progress: Optional[IndexingProgress] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> ResolutionStats:
        """Pass 2: Resolve and create all relationship edges.

        Iterates through all FileIndexResults, resolves each relationship
        target using the GlobalSymbolRegistry and ModuleResolver, and creates
        edges for resolved relationships.

        Args:
            repo_id: Repository identifier.
            all_results: List of FileIndexResults from Pass 1.
            registry: GlobalSymbolRegistry with all symbols.
            module_resolver: ModuleResolver for import resolution.
            progress: Optional IndexingProgress for tracking.
            progress_callback: Optional callback for progress updates.

        Returns:
            ResolutionStats with counts of created, external, and unresolved.
        """
        stats = ResolutionStats()

        edge_type_map = {
            RelationshipType.CALLS: GraphEdgeType.CALLS,
            RelationshipType.IMPORTS: GraphEdgeType.IMPORTS,
            RelationshipType.EXTENDS: GraphEdgeType.EXTENDS,
            RelationshipType.IMPLEMENTS: GraphEdgeType.IMPLEMENTS,
            RelationshipType.USES: GraphEdgeType.USES,
            RelationshipType.DECORATES: GraphEdgeType.DECORATES,
        }

        total_files = len(all_results)

        for file_idx, result in enumerate(all_results):
            # Update progress for each file
            if progress is not None:
                progress.resolved_files = file_idx
                progress.current_file = result.file_path
                progress.message = f"Pass 2: Resolving relationships {file_idx + 1}/{total_files} - {result.file_path}"
                self._notify_progress(progress, progress_callback)

            for rel in result.relationships:
                # Skip already-resolved intra-file relationships that were handled in Pass 1
                # Actually, in V2 we don't create edges in Pass 1, so we need to handle all

                # Get the from_node_id
                from_node_id = None
                if rel.from_symbol_id and rel.from_symbol_id in result.symbol_node_ids:
                    from_node_id = result.symbol_node_ids[rel.from_symbol_id]
                elif rel.from_symbol == "__file__":
                    # File-level relationship (imports)
                    from_node_id = result.file_node_id

                if not from_node_id:
                    stats.unresolved += 1
                    continue

                # Resolve the target
                to_node_id = self._resolve_relationship_target(
                    rel=rel,
                    source_file=result.file_path,
                    source_language=result.language,
                    registry=registry,
                    module_resolver=module_resolver,
                    result=result,
                )

                if to_node_id is None:
                    if rel.is_external:
                        stats.external += 1
                    else:
                        stats.unresolved += 1
                        if not rel.is_external:
                            logger.debug(
                                f"Could not resolve relationship: {rel.from_symbol} -> {rel.to_symbol} "
                                f"({rel.relationship_type.value}) in {result.file_path}"
                            )
                    continue

                # Create the edge
                edge_type = edge_type_map.get(rel.relationship_type)
                if not edge_type:
                    continue

                edge = GraphEdge(
                    id=f"{from_node_id}->{edge_type.value}->{to_node_id}",
                    from_node=from_node_id,
                    to_node=to_node_id,
                    edge_type=edge_type,
                    attrs={
                        "line_number": rel.line_number,
                        "confidence": rel.confidence,
                        "context": rel.context,
                    },
                )

                try:
                    self._graph_store.create_edge(edge)
                    stats.created += 1
                except Exception as e:
                    logger.debug(f"Failed to create edge {edge.id}: {e}")
                    stats.unresolved += 1

        # Final progress update
        if progress is not None:
            progress.resolved_files = total_files
            progress.current_file = None
            progress.message = (
                f"Pass 2 complete: {stats.created} edges created, "
                f"{stats.external} external, {stats.unresolved} unresolved"
            )
            self._notify_progress(progress, progress_callback)

        return stats

    def _resolve_relationship_target(
        self,
        rel: Relationship,
        source_file: str,
        source_language: Language,
        registry: GlobalSymbolRegistry,
        module_resolver: ModuleResolver,
        result: FileIndexResult,
    ) -> Optional[str]:
        """Resolve a single relationship target to node_id.

        Handles different relationship types:
        - Already-resolved intra-file: use to_symbol_id directly
        - IMPORTS: resolve module path to file node
        - CALLS/EXTENDS: resolve symbol name using registry

        Args:
            rel: The Relationship to resolve.
            source_file: Source file path for context.
            source_language: Language for module resolution.
            registry: GlobalSymbolRegistry for symbol lookup.
            module_resolver: ModuleResolver for import resolution.
            result: FileIndexResult containing local symbol mappings.

        Returns:
            Graph node ID if resolved, None otherwise.
        """
        # Handle already-resolved intra-file relationships
        if rel.is_resolved and rel.to_symbol_id:
            # Look up in local symbol_node_ids first
            if rel.to_symbol_id in result.symbol_node_ids:
                return result.symbol_node_ids[rel.to_symbol_id]
            # Try global registry
            return registry.get_node_id(rel.to_symbol_id)

        # Handle IMPORTS - resolve module path to file
        if rel.relationship_type == RelationshipType.IMPORTS:
            if rel.to_module_path:
                target_file = module_resolver.resolve_module_to_file(
                    module_path=rel.to_module_path,
                    language=source_language,
                    source_file=source_file,
                )
                if target_file:
                    # Return the file node ID
                    repo_id = result.file_node_id.split(":")[0]
                    return f"{repo_id}:{target_file}"
                else:
                    # Mark as external
                    rel.is_external = True
                    return None
            return None

        # Handle CALLS and EXTENDS - resolve symbol name
        if rel.relationship_type in (
            RelationshipType.CALLS,
            RelationshipType.EXTENDS,
            RelationshipType.IMPLEMENTS,
            RelationshipType.USES,
            RelationshipType.DECORATES,
        ):
            target_name = rel.to_symbol_name or rel.to_symbol

            if not target_name:
                return None

            # Try to resolve using the registry
            # First, try with the module path hint if available
            if rel.to_module_path:
                target_file = module_resolver.resolve_module_to_file(
                    module_path=rel.to_module_path,
                    language=source_language,
                    source_file=source_file,
                )
                if target_file:
                    # Try to find the symbol in that file
                    node_id = registry.resolve_symbol(
                        name=target_name,
                        target_file=target_file,
                    )
                    if node_id:
                        return node_id

            # Try without file filter (may be ambiguous)
            node_id = registry.resolve_symbol(name=target_name)
            if node_id:
                return node_id

            # Could not resolve - might be external
            return None

        return None

    # Smaller batch size to prevent OOM
    EMBEDDING_BATCH_SIZE = 1

    # Memory threshold (in bytes) - pause if available memory drops below this
    # Default: 500MB
    MEMORY_THRESHOLD_BYTES = 500 * 1024 * 1024

    # Use subprocess isolation for embedding (protects main process from OOM kill)
    USE_SUBPROCESS_EMBEDDING = True

    # Max consecutive OOM failures before giving up
    MAX_OOM_RETRIES = 3

    def _check_memory_available(self) -> Tuple[bool, int]:
        """Check if sufficient memory is available for embedding.

        Returns:
            Tuple of (is_safe, available_bytes).
        """
        try:
            import psutil

            mem = psutil.virtual_memory()
            available = mem.available
            return available > self.MEMORY_THRESHOLD_BYTES, available
        except ImportError:
            # psutil not available, assume OK
            return True, 0
        except Exception:
            return True, 0

    def _store_chunks_with_embeddings(
        self,
        chunks_with_file: List[Tuple[Chunk, str]],
        symbol_chunk_links: List[Tuple[str, str]],
        progress: Optional[IndexingProgress] = None,
        progress_callback: Optional[ProgressCallback] = None,
        soft_fail: bool = True,
    ) -> bool:
        """Generate embeddings and store chunks in streaming batches.

        Uses subprocess isolation to protect main process from OOM kills.

        Args:
            chunks_with_file: List of (Chunk, file_node_id) tuples.
            symbol_chunk_links: List of (symbol_node_id, chunk_node_id) tuples.
            progress: Optional IndexingProgress object for tracking.
            progress_callback: Optional callback for progress updates.
            soft_fail: If True, continue with successful chunks and track failures.

        Returns:
            True if embedding completed successfully, False if paused/stopped early.
        """
        if not chunks_with_file:
            return True

        # Use subprocess-based embedding for OOM isolation
        if self.USE_SUBPROCESS_EMBEDDING:
            return self._store_chunks_with_subprocess_embeddings(
                chunks_with_file=chunks_with_file,
                symbol_chunk_links=symbol_chunk_links,
                progress=progress,
                progress_callback=progress_callback,
            )

        # Fall back to in-process embedding (original implementation)
        self._store_chunks_with_inprocess_embeddings(
            chunks_with_file=chunks_with_file,
            symbol_chunk_links=symbol_chunk_links,
            progress=progress,
            progress_callback=progress_callback,
            soft_fail=soft_fail,
        )
        # Check if in-process method paused due to low memory
        if progress and progress.phase == IndexingPhase.PAUSED:
            return False
        return True

    def _store_chunks_with_subprocess_embeddings(
        self,
        chunks_with_file: List[Tuple[Chunk, str]],
        symbol_chunk_links: List[Tuple[str, str]],
        progress: Optional[IndexingProgress] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> bool:
        """Generate embeddings using subprocess isolation.

        This method runs embedding in a separate subprocess so that if it
        gets OOM killed (exit code 137), the main process survives and can
        save progress for resume.

        Progress is tracked in the database for resume across sessions.

        Returns:
            True if embedding completed successfully, False if paused/stopped early.
        """
        from ..processing.subprocess_embedder import SubprocessEmbedder

        total_chunks = len(chunks_with_file)
        repo_id = chunks_with_file[0][0].repo_id if chunks_with_file else None

        # Build lookup for symbol_chunk_links
        symbol_links_by_chunk: Dict[str, List[Tuple[str, str]]] = {}
        for sym_id, chunk_id in symbol_chunk_links:
            if chunk_id not in symbol_links_by_chunk:
                symbol_links_by_chunk[chunk_id] = []
            symbol_links_by_chunk[chunk_id].append((sym_id, chunk_id))

        if progress:
            progress.total_chunks_to_embed = total_chunks
            progress.processed_chunks = 0

        total_stored = 0
        total_failed = 0
        total_skipped = 0
        all_failed_chunks: List[Tuple[Chunk, str]] = []
        all_failed_errors: Dict[int, str] = {}
        expected_dims = self._dual_write_config.embedding_dimensions

        # Checkpoint interval - save progress to DB every N chunks
        CHECKPOINT_INTERVAL = 10

        # Track OOM failures for restart
        oom_count = 0

        # Check for existing embedding progress (for resume)
        start_idx = 0
        if repo_id:
            existing_progress = self._metadata_store.get_embedding_progress(repo_id)
            if existing_progress and existing_progress.get("status") in (
                "in_progress",
                "paused",
            ):
                start_idx = existing_progress.get("current_chunk_idx", 0)
                total_stored = existing_progress.get("embedded_chunks", 0)
                total_failed = existing_progress.get("failed_chunks", 0)
                total_skipped = existing_progress.get("skipped_chunks", 0)
                if start_idx > 0:
                    logger.info(
                        f"Resuming embedding from chunk {start_idx}/{total_chunks} "
                        f"(stored={total_stored}, failed={total_failed}, skipped={total_skipped})"
                    )
                    if progress:
                        progress.processed_chunks = start_idx
                        progress.message = (
                            f"Resuming from chunk {start_idx}/{total_chunks}..."
                        )
                        self._notify_progress(progress, progress_callback)
                # Update status to in_progress if it was paused
                if existing_progress.get("status") == "paused":
                    self._metadata_store.update_embedding_progress(
                        repo_id,
                        total_stored,
                        total_failed,
                        start_idx,
                        skipped_chunks=total_skipped,
                        status="in_progress",
                    )
            elif (
                not existing_progress or existing_progress.get("status") == "completed"
            ):
                # Initialize fresh embedding progress tracking
                # (or re-initialize if previous run completed but we're running again)
                self._metadata_store.init_embedding_progress(repo_id, total_chunks)

        # Get model name from embedding generator
        model_name = getattr(
            self._embedding_generator, "model_name", "jinaai/jina-embeddings-v3"
        )
        device = getattr(self._embedding_generator, "_requested_device", None)

        logger.info(
            f"Starting subprocess embedding for {total_chunks} chunks using model {model_name}"
        )

        embedder = SubprocessEmbedder(
            model_name=model_name,
            device=device,
            timeout_per_chunk=120.0,  # 2 minutes per chunk
        )

        try:
            if not embedder.start():
                logger.error(
                    "Failed to start subprocess embedder, falling back to in-process"
                )
                if repo_id:
                    self._metadata_store.update_embedding_progress(
                        repo_id,
                        0,
                        0,
                        0,
                        skipped_chunks=0,
                        status="error",
                        error_message="Failed to start subprocess embedder",
                    )
                self._store_chunks_with_inprocess_embeddings(
                    chunks_with_file=chunks_with_file,
                    symbol_chunk_links=symbol_chunk_links,
                    progress=progress,
                    progress_callback=progress_callback,
                    soft_fail=True,
                )
                return True  # In-process fallback completed

            # Get existing chunk IDs from ChromaDB to skip already-embedded chunks
            existing_chunk_ids: Set[str] = set()
            if start_idx == 0:
                # Only check ChromaDB if we're not resuming from embedding_progress
                # (embedding_progress is more accurate if available)
                try:
                    existing_chunk_ids = self._vector_store.get_existing_chunk_ids(
                        repo_id
                    )
                    if existing_chunk_ids:
                        logger.info(
                            f"Found {len(existing_chunk_ids)} existing chunks in ChromaDB, will skip them"
                        )
                except Exception as e:
                    logger.warning(
                        f"Failed to get existing chunk IDs from ChromaDB: {e}"
                    )

            for idx, (chunk, file_node_id) in enumerate(chunks_with_file):
                # Skip already-processed chunks when resuming from embedding_progress
                if idx < start_idx:
                    continue

                # Split oversized chunks
                split_chunks = self._chunker.ensure_chunk_fits(chunk)

                for split_chunk in split_chunks:
                    # Skip if chunk already exists in ChromaDB
                    if split_chunk.chunk_id in existing_chunk_ids:
                        total_skipped += 1
                        if progress:
                            progress.processed_chunks = idx + 1
                        continue

                    if progress:
                        progress.message = f"Generating embeddings: chunk {idx + 1}/{total_chunks} (stored={total_stored}, failed={total_failed}, skipped={total_skipped})..."
                        self._notify_progress(progress, progress_callback)

                    # Generate embedding in subprocess
                    embedding, error = embedder.embed_single(
                        chunk_id=split_chunk.chunk_id,
                        content=split_chunk.content,
                    )

                    if error:
                        logger.warning(
                            f"Embedding failed for chunk {split_chunk.chunk_id}: {error}"
                        )

                        # Check for OOM
                        is_oom = (
                            "OOM" in error
                            or "137" in error
                            or "killed" in error.lower()
                        )

                        if is_oom:
                            oom_count += 1
                            logger.error(
                                f"OOM detected ({oom_count}/{self.MAX_OOM_RETRIES})"
                            )

                            # Track this chunk as failed due to OOM
                            all_failed_chunks.append((split_chunk, file_node_id))
                            all_failed_errors[idx] = f"OOM: {error}"
                            total_failed += 1

                            # Update embedding progress in database
                            if repo_id:
                                self._metadata_store.update_embedding_progress(
                                    repo_id,
                                    total_stored,
                                    total_failed,
                                    idx + 1,
                                    skipped_chunks=total_skipped,
                                    status="in_progress",
                                )

                            if oom_count >= self.MAX_OOM_RETRIES:
                                logger.error(
                                    "Max OOM retries reached, saving progress and stopping"
                                )

                                # Save embedding progress as paused
                                if repo_id:
                                    self._metadata_store.update_embedding_progress(
                                        repo_id,
                                        total_stored,
                                        total_failed,
                                        idx + 1,
                                        skipped_chunks=total_skipped,
                                        status="paused",
                                        error_message=f"Stopped after {oom_count} consecutive OOM failures",
                                    )

                                # Save remaining chunks (excluding current failed one) for resume
                                remaining_chunks = chunks_with_file[idx + 1 :]
                                if repo_id and remaining_chunks:
                                    try:
                                        remaining_symbol_links = [
                                            (sym_id, cid)
                                            for sym_id, cid in symbol_chunk_links
                                            if any(
                                                cid == f"{c.repo_id}:chunk:{c.chunk_id}"
                                                for c, _ in remaining_chunks
                                            )
                                        ]
                                        self._metadata_store.save_pending_chunks(
                                            repo_id=repo_id,
                                            chunks_with_file=remaining_chunks,
                                            symbol_chunk_links=remaining_symbol_links,
                                        )
                                        logger.info(
                                            f"Saved {len(remaining_chunks)} chunks for resume"
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"Failed to save pending chunks: {e}"
                                        )

                                if progress:
                                    progress.message = f"Stopped due to repeated OOM. {total_stored} stored, {total_failed} failed, {len(remaining_chunks)} remaining for resume."
                                    progress.phase = IndexingPhase.PAUSED
                                    self._notify_progress(progress, progress_callback)
                                return False  # Paused due to OOM

                            # Restart subprocess and continue to NEXT chunk (skip the problematic one)
                            logger.info(
                                f"Restarting subprocess and skipping problematic chunk {split_chunk.chunk_id}"
                            )
                            embedder.stop()
                            gc.collect()
                            time.sleep(2)  # Give system time to reclaim memory

                            if not embedder.start():
                                logger.error("Failed to restart subprocess after OOM")
                                # Save progress and remaining chunks
                                if repo_id:
                                    self._metadata_store.update_embedding_progress(
                                        repo_id,
                                        total_stored,
                                        total_failed,
                                        idx + 1,
                                        skipped_chunks=total_skipped,
                                        status="paused",
                                        error_message="Failed to restart subprocess after OOM",
                                    )
                                remaining_chunks = chunks_with_file[idx + 1 :]
                                if repo_id and remaining_chunks:
                                    self._metadata_store.save_pending_chunks(
                                        repo_id=repo_id,
                                        chunks_with_file=remaining_chunks,
                                        symbol_chunk_links=[],
                                    )
                                if progress:
                                    progress.phase = IndexingPhase.PAUSED
                                return False  # Paused due to failed restart

                            # Continue to next chunk (don't retry the OOM-causing chunk)
                            continue

                        # Non-OOM error - just track and continue
                        all_failed_chunks.append((split_chunk, file_node_id))
                        all_failed_errors[idx] = error
                        total_failed += 1
                        continue

                    # Reset OOM counter on success
                    oom_count = 0

                    # Validate dimensions
                    if embedding and len(embedding) != expected_dims:
                        logger.error(
                            f"Dimension mismatch: expected {expected_dims}, got {len(embedding)}"
                        )
                        all_failed_chunks.append((split_chunk, file_node_id))
                        all_failed_errors[idx] = (
                            f"Dimension mismatch: {len(embedding)} vs {expected_dims}"
                        )
                        total_failed += 1
                        continue

                    # Assign embedding
                    split_chunk.embedding = embedding
                    split_chunk.token_count = self._chunker.count_tokens(
                        split_chunk.content
                    )

                    # Get symbol links
                    chunk_node_id = (
                        f"{split_chunk.repo_id}:chunk:{split_chunk.chunk_id}"
                    )
                    batch_symbol_links = symbol_links_by_chunk.pop(chunk_node_id, [])

                    # Store in Neo4j
                    try:
                        if self._dual_write_config.graph_store_chunks_enabled:
                            self._store_chunks_in_neo4j(
                                chunks_with_file=[(split_chunk, file_node_id)],
                                embeddings=[embedding],
                                symbol_chunk_links=batch_symbol_links,
                            )
                    except Exception as e:
                        logger.error(f"Failed to store in Neo4j: {e}")

                    # Store in ChromaDB
                    try:
                        self._store_chunks_in_chromadb(
                            chunks=[split_chunk],
                            embeddings=[embedding],
                        )
                        total_stored += 1
                    except Exception as e:
                        logger.error(f"Failed to store in ChromaDB: {e}")
                        all_failed_chunks.append((split_chunk, file_node_id))
                        all_failed_errors[idx] = f"ChromaDB error: {e}"
                        total_failed += 1

                if progress:
                    progress.processed_chunks = idx + 1
                    self._notify_progress(progress, progress_callback)

                # Periodic checkpoint - update embedding progress in database
                if repo_id and (idx + 1) % CHECKPOINT_INTERVAL == 0:
                    # Update embedding progress
                    self._metadata_store.update_embedding_progress(
                        repo_id,
                        total_stored,
                        total_failed,
                        idx + 1,
                        skipped_chunks=total_skipped,
                        status="in_progress",
                    )

                    # Save remaining chunks for resume
                    remaining_chunks = chunks_with_file[idx + 1 :]
                    if remaining_chunks:
                        try:
                            remaining_symbol_links = [
                                (sym_id, cid)
                                for sym_id, cid in symbol_chunk_links
                                if any(
                                    cid == f"{c.repo_id}:chunk:{c.chunk_id}"
                                    for c, _ in remaining_chunks
                                )
                            ]
                            self._metadata_store.save_pending_chunks(
                                repo_id=repo_id,
                                chunks_with_file=remaining_chunks,
                                symbol_chunk_links=remaining_symbol_links,
                            )
                            logger.debug(
                                f"Checkpoint: {len(remaining_chunks)} chunks remaining, {total_stored} stored, {total_failed} failed, {total_skipped} skipped"
                            )
                        except Exception as e:
                            logger.warning(f"Checkpoint save failed: {e}")

        finally:
            embedder.stop()

        # Mark embedding as completed
        if repo_id:
            self._metadata_store.update_embedding_progress(
                repo_id,
                total_stored,
                total_failed,
                total_chunks,
                skipped_chunks=total_skipped,
                status="completed",
            )

        # Save failed chunks for potential retry
        if all_failed_chunks and repo_id:
            try:
                self._metadata_store.save_failed_embedding_chunks(
                    repo_id=repo_id,
                    failed_chunks=all_failed_chunks,
                    errors=all_failed_errors,
                )
                logger.info(
                    f"Saved {len(all_failed_chunks)} failed chunks for potential retry"
                )
            except Exception as e:
                logger.warning(f"Failed to save failed chunks: {e}")

        # Clear pending chunks since embedding is complete
        if repo_id:
            try:
                self._metadata_store.clear_pending_chunks(repo_id)
            except Exception as e:
                logger.warning(f"Failed to clear pending chunks: {e}")

        logger.info(
            f"Subprocess embedding complete: {total_stored} stored, {total_failed} failed, {total_skipped} skipped (total: {total_chunks})"
        )
        return True  # Completed successfully

    def _store_chunks_with_inprocess_embeddings(
        self,
        chunks_with_file: List[Tuple[Chunk, str]],
        symbol_chunk_links: List[Tuple[str, str]],
        progress: Optional[IndexingProgress] = None,
        progress_callback: Optional[ProgressCallback] = None,
        soft_fail: bool = True,
    ) -> None:
        """Original in-process embedding implementation.

        WARNING: This can crash the entire process if OOM killed.
        """
        total_chunks = len(chunks_with_file)
        repo_id = chunks_with_file[0][0].repo_id if chunks_with_file else None

        # Build lookup for symbol_chunk_links
        symbol_links_by_chunk: Dict[str, List[Tuple[str, str]]] = {}
        for sym_id, chunk_id in symbol_chunk_links:
            if chunk_id not in symbol_links_by_chunk:
                symbol_links_by_chunk[chunk_id] = []
            symbol_links_by_chunk[chunk_id].append((sym_id, chunk_id))

        if progress:
            progress.total_chunks_to_embed = total_chunks
            progress.processed_chunks = 0

        total_stored = 0
        total_failed = 0
        all_failed_chunks: List[Tuple[Chunk, str]] = []
        all_failed_errors: Dict[int, str] = {}
        expected_dims = self._dual_write_config.embedding_dimensions

        # Checkpoint interval - save progress every N chunks
        CHECKPOINT_INTERVAL = 100

        # Track consecutive memory warnings
        memory_warnings = 0
        MAX_MEMORY_WARNINGS = 3

        for batch_start in range(0, total_chunks, self.EMBEDDING_BATCH_SIZE):
            batch_end = min(batch_start + self.EMBEDDING_BATCH_SIZE, total_chunks)
            batch_chunks_with_file = chunks_with_file[batch_start:batch_end]

            # Check memory before processing
            mem_ok, available_mem = self._check_memory_available()
            if not mem_ok:
                memory_warnings += 1
                logger.warning(
                    f"Low memory warning ({memory_warnings}/{MAX_MEMORY_WARNINGS}): {available_mem / 1024 / 1024:.0f}MB available"
                )

                # Force aggressive garbage collection
                gc.collect()

                # Re-check after GC
                mem_ok, available_mem = self._check_memory_available()
                if not mem_ok and memory_warnings >= MAX_MEMORY_WARNINGS:
                    logger.error(
                        f"Memory critically low ({available_mem / 1024 / 1024:.0f}MB). Saving progress and pausing."
                    )

                    # Save remaining chunks for resume
                    remaining_chunks = chunks_with_file[batch_start:]
                    if repo_id and remaining_chunks:
                        try:
                            remaining_symbol_links = [
                                (sym_id, chunk_id)
                                for sym_id, chunk_id in symbol_chunk_links
                                if any(
                                    chunk_id == f"{c.repo_id}:chunk:{c.chunk_id}"
                                    for c, _ in remaining_chunks
                                )
                            ]
                            self._metadata_store.save_pending_chunks(
                                repo_id=repo_id,
                                chunks_with_file=remaining_chunks,
                                symbol_chunk_links=remaining_symbol_links,
                            )
                            logger.info(
                                f"Saved {len(remaining_chunks)} chunks for resume due to low memory"
                            )
                        except Exception as e:
                            logger.error(f"Failed to save pending chunks: {e}")

                    # Return early - let the caller handle the partial completion
                    if progress:
                        progress.phase = IndexingPhase.PAUSED
                        progress.message = f"Paused due to low memory. {total_stored} chunks stored, {len(remaining_chunks)} remaining."
                        self._notify_progress(progress, progress_callback)
                    return  # Note: This method doesn't return a value, but the wrapper handles it
            else:
                memory_warnings = 0  # Reset counter on successful memory check

            # Split oversized chunks
            expanded_chunks_with_file = []
            for chunk, file_node_id in batch_chunks_with_file:
                split_chunks = self._chunker.ensure_chunk_fits(chunk)
                for split_chunk in split_chunks:
                    expanded_chunks_with_file.append((split_chunk, file_node_id))

            batch_chunks_with_file = expanded_chunks_with_file
            batch_chunks = [c for c, _ in batch_chunks_with_file]
            batch_contents = [chunk.content for chunk in batch_chunks]
            batch_size = len(batch_chunks)

            if progress:
                progress.message = f"Generating embeddings: chunks {batch_start + 1}-{batch_end}/{total_chunks}..."
                self._notify_progress(progress, progress_callback)

            # Generate embeddings with OOM protection
            try:
                # Force garbage collection before embedding to free memory
                gc.collect()

                if soft_fail:
                    if hasattr(
                        self._embedding_generator, "embed_batch_soft_concurrent_sync"
                    ):
                        embed_result = (
                            self._embedding_generator.embed_batch_soft_concurrent_sync(
                                batch_contents
                            )
                        )
                    else:
                        embed_result = self._embedding_generator.embed_batch_soft(
                            batch_contents
                        )

                    batch_embeddings = embed_result.embeddings

                    if embed_result.has_failures:
                        for local_idx in embed_result.failed_indices:
                            global_idx = batch_start + local_idx
                            all_failed_chunks.append(batch_chunks_with_file[local_idx])
                            all_failed_errors[global_idx] = embed_result.errors.get(
                                local_idx, "Unknown error"
                            )
                        total_failed += embed_result.failure_count

                    successful_local_indices = [
                        i
                        for i in range(batch_size)
                        if i not in embed_result.failed_indices
                    ]

                    if not successful_local_indices:
                        if progress:
                            progress.processed_chunks = batch_end
                            self._notify_progress(progress, progress_callback)
                        continue

                    batch_chunks_with_file = [
                        batch_chunks_with_file[i] for i in successful_local_indices
                    ]
                    batch_chunks = [c for c, _ in batch_chunks_with_file]
                    batch_embeddings = [
                        batch_embeddings[i] for i in successful_local_indices
                    ]
                else:
                    batch_embeddings = self._embedding_generator.embed_batch(
                        batch_contents
                    )

            except MemoryError as e:
                logger.error(
                    f"MemoryError during embedding generation at batch {batch_start}: {e}"
                )
                # Save failed chunks for retry
                for i, (chunk, file_node_id) in enumerate(batch_chunks_with_file):
                    all_failed_chunks.append((chunk, file_node_id))
                    all_failed_errors[batch_start + i] = f"MemoryError: {e}"
                total_failed += len(batch_chunks_with_file)

                # Force garbage collection
                gc.collect()

                # Save progress checkpoint
                if repo_id and all_failed_chunks:
                    try:
                        self._metadata_store.save_failed_embedding_chunks(
                            repo_id=repo_id,
                            failed_chunks=all_failed_chunks,
                            errors=all_failed_errors,
                        )
                    except Exception as save_err:
                        logger.warning(f"Failed to save failed chunks: {save_err}")

                if progress:
                    progress.processed_chunks = batch_end
                    self._notify_progress(progress, progress_callback)
                continue

            except Exception as e:
                logger.error(
                    f"Error during embedding generation at batch {batch_start}: {e}"
                )
                # Track as failed but continue
                for i, (chunk, file_node_id) in enumerate(batch_chunks_with_file):
                    all_failed_chunks.append((chunk, file_node_id))
                    all_failed_errors[batch_start + i] = str(e)
                total_failed += len(batch_chunks_with_file)

                if progress:
                    progress.processed_chunks = batch_end
                    self._notify_progress(progress, progress_callback)
                continue

            # Validate embedding dimensions
            for i, embedding in enumerate(batch_embeddings):
                if embedding is None:
                    continue
                actual_dims = len(embedding)
                if actual_dims != expected_dims:
                    raise EmbeddingDimensionError(
                        f"Embedding dimension mismatch: expected {expected_dims}, got {actual_dims}"
                    )

            # Assign embeddings and token counts
            for i, chunk in enumerate(batch_chunks):
                chunk.embedding = batch_embeddings[i]
                chunk.token_count = self._chunker.count_tokens(chunk.content)

            # Get symbol links for this batch
            batch_symbol_links = []
            for chunk, _ in batch_chunks_with_file:
                chunk_node_id = f"{chunk.repo_id}:chunk:{chunk.chunk_id}"
                if chunk_node_id in symbol_links_by_chunk:
                    batch_symbol_links.extend(symbol_links_by_chunk[chunk_node_id])
                    del symbol_links_by_chunk[chunk_node_id]

            # Store in Neo4j if enabled
            try:
                if self._dual_write_config.graph_store_chunks_enabled:
                    self._store_chunks_in_neo4j(
                        chunks_with_file=batch_chunks_with_file,
                        embeddings=batch_embeddings,
                        symbol_chunk_links=batch_symbol_links,
                    )
            except Exception as e:
                logger.error(f"Failed to store chunks in Neo4j: {e}")
                # Continue anyway - ChromaDB storage is more important

            # Store in ChromaDB
            try:
                self._store_chunks_in_chromadb(
                    chunks=batch_chunks,
                    embeddings=batch_embeddings,
                )
                total_stored += len(batch_chunks)
            except Exception as e:
                logger.error(f"Failed to store chunks in ChromaDB: {e}")
                for i, (chunk, file_node_id) in enumerate(batch_chunks_with_file):
                    all_failed_chunks.append((chunk, file_node_id))
                    all_failed_errors[batch_start + i] = f"ChromaDB error: {e}"
                total_failed += len(batch_chunks)

            if progress:
                progress.processed_chunks = batch_end
                self._notify_progress(progress, progress_callback)

            # Aggressive garbage collection after each batch
            gc.collect()

            # Periodic checkpoint save
            if repo_id and batch_end % CHECKPOINT_INTERVAL == 0:
                # Save remaining chunks as pending for resume capability
                remaining_chunks = chunks_with_file[batch_end:]
                if remaining_chunks:
                    try:
                        # Update pending chunks with remaining work
                        remaining_symbol_links = [
                            (sym_id, chunk_id)
                            for sym_id, chunk_id in symbol_chunk_links
                            if any(
                                chunk_id == f"{c.repo_id}:chunk:{c.chunk_id}"
                                for c, _ in remaining_chunks
                            )
                        ]
                        self._metadata_store.save_pending_chunks(
                            repo_id=repo_id,
                            chunks_with_file=remaining_chunks,
                            symbol_chunk_links=remaining_symbol_links,
                        )
                        logger.debug(
                            f"Checkpoint saved: {len(remaining_chunks)} chunks remaining"
                        )
                    except Exception as save_err:
                        logger.warning(f"Failed to save checkpoint: {save_err}")

        # Save failed chunks for retry
        if all_failed_chunks and repo_id:
            try:
                self._metadata_store.save_failed_embedding_chunks(
                    repo_id=repo_id,
                    failed_chunks=all_failed_chunks,
                    errors=all_failed_errors,
                )
            except Exception as e:
                logger.warning(f"Failed to save failed chunks: {e}")

        logger.info(f"Stored {total_stored} chunks ({total_failed} failed)")

    def _store_chunks_in_neo4j(
        self,
        chunks_with_file: List[Tuple[Chunk, str]],
        embeddings: List[List[float]],
        symbol_chunk_links: List[Tuple[str, str]],
    ) -> None:
        """Store chunks in Neo4j using batch upsert operations."""
        chunks_by_file: Dict[str, List[Tuple[Chunk, List[float]]]] = {}
        for i, (chunk, file_node_id) in enumerate(chunks_with_file):
            if file_node_id not in chunks_by_file:
                chunks_by_file[file_node_id] = []
            chunks_by_file[file_node_id].append((chunk, embeddings[i]))

        for file_node_id, file_chunks in chunks_by_file.items():
            sorted_chunks = sorted(file_chunks, key=lambda x: x[0].start_line)

            rows = []
            for chunk, embedding in sorted_chunks:
                chunk_node_id = f"{chunk.repo_id}:chunk:{chunk.chunk_id}"
                row = {
                    "id": chunk_node_id,
                    "repo_id": chunk.repo_id,
                    "chunk_id": chunk.chunk_id,
                    "file_path": chunk.file_path,
                    "language": chunk.language.value,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "commit_sha": chunk.commit_sha,
                    "chunk_type": chunk.chunk_type,
                    "token_count": chunk.token_count or 0,
                    "symbols_defined": chunk.symbols_defined,
                    "symbols_referenced": chunk.symbols_referenced,
                    "ts_indexed": datetime.now(UTC).isoformat(),
                }

                if self._dual_write_config.neo4j_store_chunk_content:
                    row["content"] = chunk.content

                if self._dual_write_config.neo4j_store_chunk_embeddings:
                    row["embedding"] = embedding

                rows.append(row)

            self._graph_store.upsert_chunks_with_embeddings_batch(
                file_node_id=file_node_id,
                rows=rows,
                store_content=self._dual_write_config.neo4j_store_chunk_content,
                store_embedding=self._dual_write_config.neo4j_store_chunk_embeddings,
            )

            if len(sorted_chunks) > 1:
                next_chunk_edges = []
                for i in range(len(sorted_chunks) - 1):
                    from_chunk = sorted_chunks[i][0]
                    to_chunk = sorted_chunks[i + 1][0]
                    next_chunk_edges.append(
                        {
                            "from_chunk_id": f"{from_chunk.repo_id}:chunk:{from_chunk.chunk_id}",
                            "to_chunk_id": f"{to_chunk.repo_id}:chunk:{to_chunk.chunk_id}",
                        }
                    )
                self._graph_store.upsert_next_chunk_edges_batch(edges=next_chunk_edges)

        if symbol_chunk_links:
            links = [
                {"symbol_id": symbol_id, "chunk_id": chunk_id}
                for symbol_id, chunk_id in symbol_chunk_links
            ]
            self._graph_store.upsert_symbol_chunk_links_batch(links=links)

    def _store_chunks_in_chromadb(
        self,
        chunks: List[Chunk],
        embeddings: List[List[float]],
    ) -> None:
        """Store chunks in ChromaDB with cross-store reference metadata."""
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        contents = [chunk.content for chunk in chunks]

        metadatas = []
        for chunk in chunks:
            neo4j_chunk_node_id = f"{chunk.repo_id}:chunk:{chunk.chunk_id}"
            metadatas.append(
                {
                    "repo_id": chunk.repo_id,
                    "file_path": chunk.file_path,
                    "language": chunk.language.value,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "symbols_defined": chunk.symbols_defined,
                    "symbols_referenced": chunk.symbols_referenced,
                    "commit_sha": chunk.commit_sha,
                    "ts_indexed": datetime.now(UTC).isoformat(),
                    "neo4j_chunk_node_id": neo4j_chunk_node_id,
                }
            )

        self._vector_store.upsert_batch(
            chunk_ids=chunk_ids,
            embeddings=embeddings,
            metadatas=metadatas,
            contents=contents,
        )

    def _notify_progress(
        self,
        progress: IndexingProgress,
        callback: Optional[ProgressCallback],
    ) -> None:
        """Notify progress callback if provided and persist progress."""
        try:
            self._metadata_store.save_indexing_progress(
                repo_id=progress.repo_id,
                phase=progress.phase.value,
                total_files=progress.total_files,
                processed_files=progress.processed_files,
                current_file=progress.current_file,
                total_chunks=progress.total_chunks,
                total_symbols=progress.total_symbols,
                total_relationships=progress.total_relationships,
                embedded_chunks=getattr(progress, "processed_chunks", 0),
                total_chunks_to_embed=getattr(progress, "total_chunks_to_embed", 0),
                message=progress.message,
            )
        except Exception as e:
            logger.warning(f"Failed to persist progress: {e}")

        if callback:
            try:
                callback(progress)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

    def _compute_file_hash(self, file_path: str) -> str:
        """Compute SHA-256 hash of a file's content."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def _ensure_repo_metadata(
        self,
        repo_id: str,
        git_url: str,
        branch: str,
        local_path: str,
    ) -> None:
        """Ensure repository metadata exists in the metadata store."""
        existing = self._metadata_store.get_repo(repo_id)
        if not existing:
            repo_metadata = RepoMetadata(
                repo_id=repo_id,
                git_url=git_url,
                default_branch=branch,
                local_path=local_path,
                status=RepoStatus.PENDING,
            )
            self._metadata_store.create_repo(repo_metadata)

    def _create_repo_node(
        self,
        repo_id: str,
        git_url: str,
        branch: str,
    ) -> str:
        """Create a Repo node in the graph store."""
        node = GraphNode(
            id=repo_id,
            type=GraphNodeType.REPO,
            repo_id=repo_id,
            attrs={
                "git_url": git_url,
                "default_branch": branch,
            },
            summary=f"Repository: {git_url}",
        )
        self._graph_store.create_node(node)
        return repo_id

    def _create_directory_nodes(
        self,
        repo_id: str,
        files: List[str],
    ) -> None:
        """Create Directory nodes for all directories containing files."""
        directories: set = set()
        for file_path in files:
            parts = file_path.split("/")
            for i in range(1, len(parts)):
                dir_path = "/".join(parts[:i])
                directories.add(dir_path)

        sorted_dirs = sorted(directories)
        created_dirs: set = set()

        for dir_path in sorted_dirs:
            dir_node_id = f"{repo_id}:dir:{dir_path}"

            dir_node = GraphNode(
                id=dir_node_id,
                type=GraphNodeType.DIRECTORY,
                repo_id=repo_id,
                attrs={
                    "path": dir_path,
                    "name": dir_path.split("/")[-1],
                },
                summary=f"Directory: {dir_path}",
            )
            self._graph_store.create_node(dir_node)
            created_dirs.add(dir_path)

            parts = dir_path.split("/")
            if len(parts) == 1:
                parent_id = repo_id
            else:
                parent_path = "/".join(parts[:-1])
                parent_id = f"{repo_id}:dir:{parent_path}"

            edge = GraphEdge(
                id=f"{parent_id}->CONTAINS->{dir_node_id}",
                from_node=parent_id,
                to_node=dir_node_id,
                edge_type=GraphEdgeType.CONTAINS,
                attrs={},
            )
            self._graph_store.create_edge(edge)

        logger.debug(f"Created {len(created_dirs)} directory nodes for repo {repo_id}")

    def _get_parent_directory_node_id(self, repo_id: str, file_path: str) -> str:
        """Get the node ID of the parent directory for a file."""
        parts = file_path.split("/")
        if len(parts) == 1:
            return repo_id
        else:
            parent_path = "/".join(parts[:-1])
            return f"{repo_id}:dir:{parent_path}"

    def _create_file_node(
        self,
        repo_id: str,
        file_path: str,
    ) -> str:
        """Create a File node and CONTAINS edge from parent Directory."""
        file_node_id = f"{repo_id}:{file_path}"

        file_node = GraphNode(
            id=file_node_id,
            type=GraphNodeType.FILE,
            repo_id=repo_id,
            attrs={"file_path": file_path},
            summary=f"File: {file_path}",
        )
        self._graph_store.create_node(file_node)

        parent_id = self._get_parent_directory_node_id(repo_id, file_path)
        edge = GraphEdge(
            id=f"{parent_id}->CONTAINS->{file_node_id}",
            from_node=parent_id,
            to_node=file_node_id,
            edge_type=GraphEdgeType.CONTAINS,
            attrs={},
        )
        self._graph_store.create_edge(edge)

        return file_node_id

    def _create_symbol_node(
        self,
        repo_id: str,
        file_path: str,
        symbol: SymbolInfo,
        file_node_id: str,
    ) -> str:
        """Create a Symbol node with enhanced metadata."""
        symbol_node_id = f"{repo_id}:{symbol.symbol_id}"

        attrs = {
            "name": symbol.name,
            "kind": symbol.kind.value,
            "file_path": file_path,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "visibility": symbol.visibility.value,
            "docstring": symbol.docstring,
            "signature": symbol.signature,
            "return_type": symbol.return_type,
            "is_async": symbol.is_async,
            "is_static": symbol.is_static,
            "is_abstract": symbol.is_abstract,
            "decorators": ",".join(symbol.decorators) if symbol.decorators else None,
            "base_classes": ",".join(symbol.base_classes)
            if symbol.base_classes
            else None,
            "complexity": symbol.complexity,
        }

        summary_parts = [f"{symbol.kind.value}: {symbol.name}"]
        if symbol.signature:
            summary_parts.append(f"Signature: {symbol.signature}")
        if symbol.docstring:
            doc_preview = (
                symbol.docstring[:100] + "..."
                if len(symbol.docstring) > 100
                else symbol.docstring
            )
            summary_parts.append(doc_preview)

        symbol_node = GraphNode(
            id=symbol_node_id,
            type=GraphNodeType.SYMBOL,
            repo_id=repo_id,
            attrs=attrs,
            summary=" | ".join(summary_parts),
        )
        self._graph_store.create_node(symbol_node)

        edge = GraphEdge(
            id=f"{file_node_id}->CONTAINS->{symbol_node_id}",
            from_node=file_node_id,
            to_node=symbol_node_id,
            edge_type=GraphEdgeType.CONTAINS,
            attrs={},
        )
        self._graph_store.create_edge(edge)

        return symbol_node_id

    def _regenerate_chunks_from_indexed_files(
        self,
        repo_id: str,
        repo_path: str,
        all_files: List[str],
        commit_sha: str,
        progress: Optional[IndexingProgress] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Tuple[List[Tuple[Chunk, str]], List[Tuple[str, str]]]:
        """Regenerate chunks from already-indexed files for embedding.

        This method is used when resuming and all files are indexed but
        embeddings are missing. It re-reads the files and creates chunks
        without re-creating graph nodes (which already exist).

        Args:
            repo_id: Repository identifier.
            repo_path: Local path to the repository.
            all_files: List of all file paths to process.
            commit_sha: Current commit SHA.
            progress: Optional progress tracker.
            progress_callback: Optional callback for progress updates.

        Returns:
            Tuple of (chunks_with_file, symbol_chunk_links).
        """
        logger.info(
            f"Regenerating chunks from {len(all_files)} indexed files for repo {repo_id}"
        )

        all_chunks: List[Tuple[Chunk, str]] = []
        all_symbol_chunk_links: List[Tuple[str, str]] = []

        processed = 0
        for file_path in all_files:
            full_path = Path(repo_path) / file_path

            if not full_path.exists():
                logger.warning(f"File not found during chunk regeneration: {file_path}")
                continue

            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()

                language = self._language_parser.detect_language(file_path, content)

                # Parse and extract symbols if supported
                symbols: List[SymbolInfo] = []
                tree = None

                if self._language_parser.supports_language(language):
                    parse_result = self._language_parser.parse(content, language)
                    if parse_result and parse_result.success:
                        tree = parse_result.tree
                        symbols, _ = self._symbol_extractor.extract_all(
                            tree, file_path, language, content
                        )

                # Create chunks
                if tree and symbols:
                    chunks = self._chunker.chunk_code(
                        content=content,
                        tree=tree,
                        symbols=symbols,
                        repo_id=repo_id,
                        file_path=file_path,
                        language=language,
                        commit_sha=commit_sha,
                    )
                else:
                    chunks = self._chunker.chunk_text(
                        content=content,
                        repo_id=repo_id,
                        file_path=file_path,
                        commit_sha=commit_sha,
                    )

                # Use existing file_node_id format
                file_node_id = f"{repo_id}:{file_path}"

                # Prepare chunk data with file association
                for chunk in chunks:
                    all_chunks.append((chunk, file_node_id))

                # Build symbol-to-chunk links (symbols already exist in graph)
                for chunk in chunks:
                    chunk_node_id = f"{repo_id}:chunk:{chunk.chunk_id}"
                    for symbol_name in chunk.symbols_defined:
                        for symbol in symbols:
                            if symbol.name == symbol_name:
                                symbol_node_id = f"{repo_id}:{symbol.symbol_id}"
                                all_symbol_chunk_links.append(
                                    (symbol_node_id, chunk_node_id)
                                )
                                break

                processed += 1
                if progress and progress_callback and processed % 100 == 0:
                    progress.message = (
                        f"Regenerating chunks: {processed}/{len(all_files)} files..."
                    )
                    self._notify_progress(progress, progress_callback)

            except Exception as e:
                logger.warning(f"Failed to regenerate chunks for {file_path}: {e}")
                continue

        logger.info(f"Regenerated {len(all_chunks)} chunks from {processed} files")
        return all_chunks, all_symbol_chunk_links

    def get_repo_status(self, repo_id: str) -> Optional[RepoStatus]:
        """Get the current status of a repository."""
        repo = self._metadata_store.get_repo(repo_id)
        return repo.status if repo else None

    def is_repo_ready(self, repo_id: str) -> bool:
        """Check if a repository is ready for querying."""
        status = self.get_repo_status(repo_id)
        return status == RepoStatus.READY
