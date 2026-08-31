"""Repository indexing endpoints (sections 12, 13 and 29)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_session, settings_dependency
from apps.api.schemas import IndexRepositoryRequest, RepositoryOut
from core.config import Settings
from persistence.repositories import RepositoryRepository
from policies.evaluator import rules_as_dicts
from retrieval.ingestion.indexer import index_repository

router = APIRouter(prefix="/api/v1", tags=["repositories"])


@router.post("/repositories/index", response_model=RepositoryOut)
async def index(
    request: IndexRepositoryRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dependency),
) -> RepositoryOut:
    path = Path(request.path).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"path does not exist: {request.path}")

    repository = await index_repository(
        session, url=request.url, path=path, default_branch=request.default_branch
    )
    return RepositoryOut(
        id=repository.id,
        url=repository.url,
        path=repository.path,
        default_branch=repository.default_branch,
        chunk_count=repository.chunk_count,
        indexed_at=repository.indexed_at,
    )


@router.get("/repositories", response_model=list[RepositoryOut])
async def list_repositories(session: AsyncSession = Depends(get_session)) -> list[RepositoryOut]:
    repositories = await RepositoryRepository(session).list()
    return [
        RepositoryOut(
            id=repository.id,
            url=repository.url,
            path=repository.path,
            default_branch=repository.default_branch,
            chunk_count=repository.chunk_count,
            indexed_at=repository.indexed_at,
        )
        for repository in repositories
    ]


@router.get("/repositories/{repository_id}", response_model=RepositoryOut)
async def get_repository(
    repository_id: str, session: AsyncSession = Depends(get_session)
) -> RepositoryOut:
    repository = await RepositoryRepository(session).get(repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="repository not found")
    return RepositoryOut(
        id=repository.id,
        url=repository.url,
        path=repository.path,
        default_branch=repository.default_branch,
        chunk_count=repository.chunk_count,
        indexed_at=repository.indexed_at,
    )


@router.get("/policies")
async def get_policies() -> list[dict]:
    """The rules a reviewer is trusting - visible, not buried in a prompt."""
    return rules_as_dicts()
