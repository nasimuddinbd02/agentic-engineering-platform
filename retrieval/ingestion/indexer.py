"""Indexing pipeline: scan -> parse -> chunk -> store (section 13).

Embeddings are optional.  Levels 1-3 of section 12 (lexical, symbol,
dependency) work with no vectors at all, and the platform ships in that state;
passing an embedder turns on level 4 without changing anything else.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from core.ids import new_id
from core.logging import get_logger
from persistence.models import CodeChunk, Repository
from persistence.repositories import CodeChunkRepository, RepositoryRepository
from retrieval.ingestion.chunker import chunk_file
from retrieval.ingestion.scanner import detect_languages, scan_repository
from retrieval.search.vector import Embedder

log = get_logger(__name__)


async def index_repository(
    session: AsyncSession,
    *,
    url: str,
    path: Path,
    default_branch: str = "main",
    embedder: Embedder | None = None,
) -> Repository:
    files = scan_repository(path)
    repositories = RepositoryRepository(session)
    repository = await repositories.upsert(
        url=url,
        path=str(Path(path).resolve()),
        default_branch=default_branch,
        languages=detect_languages(files),
    )

    chunks: list[CodeChunk] = []
    for file in files:
        for chunk in chunk_file(file):
            chunks.append(
                CodeChunk(
                    id=new_id("chunk"),
                    repository_id=repository.id,
                    file_path=chunk.file_path,
                    symbol_name=chunk.symbol_name,
                    symbol_kind=chunk.symbol_kind,
                    language=chunk.language,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    embedding=None,
                    meta={"lines": chunk.end_line - chunk.start_line + 1},
                )
            )

    if embedder is not None:
        vectors = await embedder.embed([chunk.content for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.embedding = vector

    stored = await CodeChunkRepository(session).replace_all(repository.id, chunks)
    await repositories.mark_indexed(repository.id, stored)
    log.info(
        "retrieval.indexed",
        repository=url,
        files=len(files),
        chunks=stored,
        embedded=embedder is not None,
    )
    return repository
