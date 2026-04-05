"""
Ingest workflow handler.

Handles repository cloning and indexing workflows over WebSocket with
thread-safe progress bridging from synchronous operations.
"""

import asyncio
import os
import time
import traceback

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.graph_kb.repositories.repo_fetcher import AuthenticationError, CloneError
from graph_kb_api.websocket.handlers.base import (
    _debug_log,
    logger,
)
from graph_kb_api.websocket.manager import manager
from graph_kb_api.websocket.progress import (
    ProgressEvent,
    ThreadSafeBridge,
    consume_progress_queue,
)
from graph_kb_api.websocket.protocol import IngestPayload


async def handle_ingest_workflow(
    client_id: str,
    workflow_id: str,
    payload: IngestPayload,
) -> None:
    """Handle the ingest workflow with progress updates.

    Uses :class:`ThreadSafeBridge` and :func:`consume_progress_queue` to
    safely relay progress events from synchronous clone/index threads to
    the async WebSocket layer.
    """
    from graph_kb_api.graph_kb.models.enums import IndexingPhase
    from graph_kb_api.graph_kb.models.ingestion import IndexingProgress

    logger.info(
        "Ingest workflow started | workflow_id=%s client_id=%s git_url=%s branch=%s",
        workflow_id,
        client_id,
        payload.git_url,
        payload.branch,
    )
    _debug_log(
        "INGEST_ENTRY",
        workflow_id=workflow_id,
        client_id=client_id,
        git_url=payload.git_url,
        branch=payload.branch,
        force_reindex=payload.force_reindex,
    )

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    bridge = ThreadSafeBridge(loop, queue, workflow_id=workflow_id)

    consumer = asyncio.create_task(
        consume_progress_queue(queue, client_id, workflow_id, manager)
    )
    logger.info("Progress queue and consumer created | workflow_id=%s", workflow_id)

    try:
        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "phase": "cloning",
                "step": "cloning",
                "progress_percent": -1,
                "message": f"Cloning {payload.git_url}...",
            },
        )

        facade = get_graph_kb_facade()
        _debug_log(
            "FACADE_RETRIEVED",
            workflow_id=workflow_id,
            facade_initialized=getattr(facade, "is_initialized", "unknown"),
        )

        ingestion_service = facade.ingestion_service
        if not ingestion_service:
            _debug_log("INGESTION_SERVICE_MISSING", workflow_id=workflow_id)
            raise RuntimeError("Ingestion service not available")
        _debug_log("INGESTION_SERVICE_OK", workflow_id=workflow_id)

        repo_fetcher = facade.repo_fetcher
        if not repo_fetcher:
            _debug_log("REPO_FETCHER_MISSING", workflow_id=workflow_id)
            raise RuntimeError("Repo fetcher not available")
        _debug_log("REPO_FETCHER_OK", workflow_id=workflow_id)

        # Phase map for translating IndexingPhase enums to string phases
        phase_map = {
            IndexingPhase.INITIALIZING: "initializing",
            IndexingPhase.DISCOVERING_FILES: "discovering",
            IndexingPhase.INDEXING_FILES: "indexing",
            IndexingPhase.RESOLVING_RELATIONSHIPS: "building",
            IndexingPhase.GENERATING_EMBEDDINGS: "embedding",
            IndexingPhase.BUILDING_GRAPH: "building",
            IndexingPhase.FINALIZING: "finalizing",
            IndexingPhase.COMPLETED: "finalizing",
            IndexingPhase.PAUSED: "finalizing",
            IndexingPhase.ERROR: "error",
        }

        # -- Clone progress callback (runs in a worker thread) ---------------
        def clone_progress(phase: str, current: int, total: int, message: str) -> None:
            pct = (current / total * 100) if total > 0 else -1
            logger.debug(
                "Clone progress | workflow_id=%s phase=%s progress=%d/%d (%.1f%%) message=%s",
                workflow_id,
                phase,
                current,
                total,
                pct if pct >= 0 else 0,
                message,
            )
            # Build a human-readable message from the git phase
            phase_labels = {
                "counting_objects": "Counting objects",
                "compressing_objects": "Compressing objects",
                "receiving_objects": "Receiving objects",
                "resolving_deltas": "Resolving deltas",
                "checking_out": "Checking out files",
                "writing_objects": "Writing objects",
                "finding_sources": "Finding sources",
            }
            label = phase_labels.get(phase, "Cloning")
            if total > 0:
                display_msg = f"{label}: {current}/{total} ({pct:.0f}%)"
            else:
                display_msg = f"{label}..."
            bridge.send(
                {
                    "phase": "cloning",
                    "step": "cloning",
                    "progress_percent": pct,
                    "message": display_msg,
                    "clone_phase": phase,
                }
            )

        repo_id = repo_fetcher.create_repo_id(payload.git_url)
        logger.info("Resolved repo_id=%s for %s", repo_id, payload.git_url)
        _debug_log("REPO_ID_RESOLVED", workflow_id=workflow_id, repo_id=repo_id)

        clone_start = time.monotonic()

        repo_exists = repo_fetcher.repo_exists(repo_id)
        _debug_log(
            "REPO_EXISTS_CHECK",
            workflow_id=workflow_id,
            repo_id=repo_id,
            exists=repo_exists,
        )

        auth_token = os.environ.get("GITHUB_TOKEN") or None
        logger.info(
            "Auth token present=%s length=%s | workflow_id=%s",
            auth_token is not None,
            len(auth_token) if auth_token else 0,
            workflow_id,
        )

        if repo_exists:
            logger.info(
                "Repository already exists locally, updating | repo_id=%s branch=%s",
                repo_id,
                payload.branch or "main",
            )
            repo_info = await asyncio.to_thread(
                repo_fetcher.update_repo,
                repo_id=repo_id,
                branch=payload.branch or "main",
                auth_token=auth_token,
            )
        else:
            logger.info(
                "Repository not found locally, cloning | repo_id=%s url=%s branch=%s",
                repo_id,
                payload.git_url,
                payload.branch or "main",
            )
            repo_info = await asyncio.to_thread(
                repo_fetcher.clone_repo,
                repo_url=payload.git_url,
                branch=payload.branch or "main",
                auth_token=auth_token,
                progress_callback=clone_progress,
            )

        clone_elapsed = time.monotonic() - clone_start
        repo_path = repo_info.local_path
        commit_sha = repo_info.commit_sha

        logger.info(
            "Clone/update complete | repo_id=%s commit=%s path=%s elapsed=%.2fs",
            repo_id,
            commit_sha[:8] if commit_sha else "unknown",
            repo_path,
            clone_elapsed,
        )
        _debug_log(
            "CLONE_COMPLETE",
            workflow_id=workflow_id,
            repo_id=repo_id,
            repo_path=repo_path,
            commit_sha=commit_sha,
            elapsed=f"{clone_elapsed:.2f}s",
        )

        await manager.send_event(
            client_id=client_id,
            event_type="progress",
            workflow_id=workflow_id,
            data={
                "phase": "discovering",
                "step": "discovering",
                "progress_percent": -1,
                "message": "Discovering files...",
            },
        )

        # -- Index progress callback (runs in a worker thread) ---------------
        _last_log_time = [0.0]

        def index_progress(progress: IndexingProgress) -> None:
            phase_str = phase_map.get(progress.phase, progress.phase.value)

            # Log at INFO every 5s so progress is visible in container logs
            now = time.monotonic()
            if now - _last_log_time[0] >= 5.0 or progress.processed_files <= 1:
                _last_log_time[0] = now
                logger.info(
                    "Index progress | workflow_id=%s phase=%s files=%d/%d "
                    "chunks=%d symbols=%d file=%s",
                    workflow_id,
                    phase_str,
                    progress.processed_files,
                    progress.total_files,
                    progress.total_chunks,
                    progress.total_symbols,
                    progress.current_file or "",
                )
            else:
                logger.debug(
                    "Index progress | workflow_id=%s phase=%s files=%d/%d chunks=%d file=%s",
                    workflow_id,
                    phase_str,
                    progress.processed_files,
                    progress.total_files,
                    progress.total_chunks,
                    progress.current_file or "",
                )

            # Build a descriptive message based on the current phase
            if progress.phase == IndexingPhase.GENERATING_EMBEDDINGS:
                msg = f"Embedding chunks: {progress.processed_chunks}/{progress.total_chunks_to_embed}"
            elif progress.phase == IndexingPhase.RESOLVING_RELATIONSHIPS:
                msg = f"Resolving relationships: {progress.resolved_files}/{progress.total_files_to_resolve} files"
            elif progress.phase == IndexingPhase.INDEXING_FILES:
                current = progress.current_file or ""
                short_file = current.rsplit("/", 1)[-1] if current else ""
                msg = (
                    f"Indexing files: {progress.processed_files}/{progress.total_files}"
                )
                if short_file:
                    msg += f" — {short_file}"
            elif progress.message:
                msg = progress.message
            else:
                msg = f"Processing {progress.current_file or 'files'}..."

            bridge.send(
                ProgressEvent(
                    phase=phase_str,
                    message=msg,
                    progress_percent=round(progress.progress_percent, 1),
                    detail={
                        "repo_id": progress.repo_id,
                        "total_files": progress.total_files,
                        "processed_files": progress.processed_files,
                        "total_chunks": progress.total_chunks,
                        "total_symbols": progress.total_symbols,
                        "current_file": progress.current_file,
                        "processed_chunks": progress.processed_chunks,
                        "total_chunks_to_embed": progress.total_chunks_to_embed,
                        "failed_files": progress.failed_files,
                    },
                ).to_send_data()
            )

        logger.info(
            "Starting indexing | repo_id=%s workflow_id=%s", repo_id, workflow_id
        )
        _debug_log(
            "INDEX_START",
            workflow_id=workflow_id,
            repo_id=repo_id,
            repo_path=repo_path,
            commit_sha=commit_sha,
        )
        index_start = time.monotonic()

        result = await asyncio.to_thread(
            ingestion_service.index_repo,
            repo_id=repo_id,
            repo_path=repo_path,
            git_url=payload.git_url,
            branch=payload.branch,
            commit_sha=commit_sha,
            progress_callback=index_progress,
            resume=payload.resume,
        )

        index_elapsed = time.monotonic() - index_start
        total_elapsed = clone_elapsed + index_elapsed

        _debug_log(
            "INDEX_COMPLETE",
            workflow_id=workflow_id,
            repo_id=repo_id,
            total_files=result.total_files,
            total_chunks=result.total_chunks,
            total_symbols=result.total_symbols,
            total_relationships=result.total_relationships,
            index_time=f"{index_elapsed:.2f}s",
            total_time=f"{total_elapsed:.2f}s",
        )

        logger.info(
            "Ingest workflow complete | workflow_id=%s repo_id=%s "
            "files=%d chunks=%d symbols=%d relationships=%d "
            "clone_time=%.2fs index_time=%.2fs total_time=%.2fs",
            workflow_id,
            result.repo_id if hasattr(result, "repo_id") else repo_id,
            result.total_files,
            result.total_chunks,
            result.total_symbols,
            result.total_relationships,
            clone_elapsed,
            index_elapsed,
            total_elapsed,
        )

        await manager.send_event(
            client_id=client_id,
            event_type="complete",
            workflow_id=workflow_id,
            data={
                "repo_id": result.repo_id if hasattr(result, "repo_id") else repo_id,
                "message": "Repository indexed successfully",
                "stats": {
                    "total_files": result.total_files,
                    "total_chunks": result.total_chunks,
                    "total_symbols": result.total_symbols,
                    "total_relationships": result.total_relationships,
                },
            },
        )

    except AuthenticationError as e:
        logger.error(f"Ingest auth error: {e}")
        _debug_log(
            "INGEST_ERROR",
            workflow_id=workflow_id,
            error_type="AuthenticationError",
            error_message=str(e),
        )
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={"message": str(e), "code": "AUTH_ERROR"},
        )
    except CloneError as e:
        logger.error(f"Ingest clone error: {e}")
        _debug_log(
            "INGEST_ERROR",
            workflow_id=workflow_id,
            error_type="CloneError",
            error_message=str(e),
        )
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={"message": str(e), "code": "CLONE_ERROR"},
        )
    except Exception as e:
        logger.error(f"Ingest workflow error: {e}", exc_info=True)
        _debug_log(
            "INGEST_ERROR",
            workflow_id=workflow_id,
            error_type=type(e).__name__,
            error_message=str(e),
            traceback=traceback.format_exc(),
        )
        await manager.send_event(
            client_id=client_id,
            event_type="error",
            workflow_id=workflow_id,
            data={"message": str(e), "code": "WORKFLOW_ERROR"},
        )
    finally:
        bridge_stats = bridge.get_stats()
        logger.info(
            "Ingest workflow teardown | workflow_id=%s bridge_stats=%s",
            workflow_id,
            bridge_stats,
        )
        queue.put_nowait(None)  # sentinel to stop consumer
        await consumer
        await manager.complete_workflow(workflow_id)
