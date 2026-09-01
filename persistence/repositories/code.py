"""Repository + code-chunk persistence for the RAG layer (section 13)."""

from __future__ import annotations

import hashlib

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.time import utcnow
from persistence.models import CodeChunk, Repository


def repository_id_for(url: str) -> str:
    return "repo-" + hashlib.sha256(url.encode()).hexdigest()[:16]


class RepositoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        url: str,
        path: str,
        default_branch: str = "main",
        languages: list[str] | None = None,
    ) -> Repository:
        identifier = repository_id_for(url)
        repo = await self.session.get(Repository, identifier)
        if repo is None:
            repo = Repository(id=identifier, url=url, path=path)
            self.session.add(repo)
        repo.path = path
        repo.default_branch = default_branch
        if languages is not None:
            repo.languages = languages
        await self.session.flush()
        return repo

    async def get(self, identifier: str) -> Repository | None:
        return await self.session.get(Repository, identifier)

    async def get_by_url(self, url: str) -> Repository | None:
        return await self.session.get(Repository, repository_id_for(url))

    async def list(self) -> list[Repository]:
        return list((await self.session.scalars(select(Repository))).all())

    async def mark_indexed(self, identifier: str, chunk_count: int) -> None:
        repo = await self.session.get(Repository, identifier)
        if repo is None:
            return
        repo.indexed_at = utcnow()
        repo.chunk_count = chunk_count


class CodeChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def replace_all(self, repository_id: str, chunks: list[CodeChunk]) -> int:
        await self.session.execute(
            delete(CodeChunk).where(CodeChunk.repository_id == repository_id)
        )
        for chunk in chunks:
            self.session.add(chunk)
        await self.session.flush()
        return len(chunks)

    async def all_for(self, repository_id: str) -> list[CodeChunk]:
        stmt = select(CodeChunk).where(CodeChunk.repository_id == repository_id)
        return list((await self.session.scalars(stmt)).all())

    async def by_symbol(self, repository_id: str, symbol: str, limit: int = 20) -> list[CodeChunk]:
        stmt = (
            select(CodeChunk)
            .where(CodeChunk.repository_id == repository_id, CodeChunk.symbol_name == symbol)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def count(self, repository_id: str) -> int:
        chunks = await self.all_for(repository_id)
        return len(chunks)
