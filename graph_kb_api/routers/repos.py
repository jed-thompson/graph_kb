"""
Repository management router.

Provides endpoints for listing, retrieving, and deleting indexed repositories.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from graph_kb_api.dependencies import get_graph_kb_facade
from graph_kb_api.schemas.repos import RepoListResponse, RepoResponse, RepoStatus

router = APIRouter(prefix="/repos", tags=["Repositories"])


@router.get("", response_model=RepoListResponse)
async def list_repositories(
    status: Optional[RepoStatus] = Query(None, description="Filter by status"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit"),
    facade=Depends(get_graph_kb_facade),
):
    """
    List all indexed repositories.

    Optionally filter by status and paginate results.
    """
    try:
        # Get metadata store from facade
        metadata_store = facade.metadata_store
        if not metadata_store:
            return RepoListResponse(repos=[], total=0)

        # Get all repositories
        all_repos = metadata_store.list_repos()

        # Filter by status if specified
        if status:
            all_repos = [r for r in all_repos if r.status.value == status.value]

        total = len(all_repos)

        # Apply pagination
        repos = all_repos[offset : offset + limit]

        # Convert to response models
        repo_responses = [
            RepoResponse(
                id=r.repo_id,
                git_url=r.git_url,
                branch=r.default_branch,
                status=RepoStatus(r.status.value),
                last_indexed_at=r.last_indexed_at,
                commit_sha=r.last_indexed_commit,
                error_message=r.error_message,
            )
            for r in repos
        ]

        return RepoListResponse(
            repos=repo_responses, total=total, offset=offset, limit=limit
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list repositories: {e}")


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repository(
    repo_id: str,
    facade=Depends(get_graph_kb_facade),
):
    """
    Get details for a specific repository.
    """
    try:
        metadata_store = facade.metadata_store
        if not metadata_store:
            raise HTTPException(
                status_code=404, detail=f"Repository {repo_id} not found"
            )

        repo = metadata_store.get_repository(repo_id)
        if not repo:
            raise HTTPException(
                status_code=404, detail=f"Repository {repo_id} not found"
            )

        return RepoResponse(
            id=repo.repo_id,
            git_url=repo.git_url,
            branch=repo.default_branch,
            status=RepoStatus(repo.status.value),
            last_indexed_at=repo.last_indexed_at,
            commit_sha=repo.last_indexed_commit,
            error_message=repo.error_message,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get repository: {e}")


@router.delete("/{repo_id}", status_code=204)
async def delete_repository(
    repo_id: str,
    facade=Depends(get_graph_kb_facade),
):
    """
    Delete a repository and all its indexed data.

    This removes the repository from:
    - Graph store (Neo4j nodes and relationships)
    - Vector store (embeddings)
    - Metadata store (repository metadata)
    """
    try:
        metadata_store = facade.metadata_store

        # Verify repo exists
        if metadata_store:
            repo = metadata_store.get_repository(repo_id)
            if not repo:
                raise HTTPException(
                    status_code=404, detail=f"Repository {repo_id} not found"
                )

        # Delete from graph store
        if facade.graph_store:
            facade.graph_store.delete_repository(repo_id)

        # Delete from vector store
        if facade.vector_store:
            facade.vector_store.delete_repository(repo_id)

        # Delete from metadata store
        if metadata_store:
            metadata_store.delete_repository(repo_id)

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete repository: {e}")
