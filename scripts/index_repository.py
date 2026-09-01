"""Index a repository for retrieval (sections 12 and 13).

    python -m scripts.index_repository --path ./.sandbox/order-service

Levels 1-3 of section 12 need no index at all - they run directly against the
working tree.  This builds the chunk table that levels 4 and 5 use, and shows
what the retriever would return for a query.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))


async def run(path: Path, url: str | None, query: str | None) -> None:
    from core.config import get_settings
    from persistence.db import create_schema, dispose_engine, session_scope
    from persistence.repositories import CodeChunkRepository
    from retrieval.ingestion.indexer import index_repository
    from retrieval.search.hybrid import HybridRetriever

    settings = get_settings()
    await create_schema(settings)

    async with session_scope(settings) as session:
        repository = await index_repository(session, url=url or path.as_uri(), path=path)
        print(f"indexed {repository.url}")
        print(f"  chunks: {repository.chunk_count}")
        print(f"  languages: {', '.join(repository.languages) or '(none)'}")

    if query:
        async with session_scope(settings) as session:
            chunks = await CodeChunkRepository(session).all_for(repository.id)
        results = await HybridRetriever(chunks).search(query, limit=8)
        print(f"\ntop results for {query!r}:")
        for position, result in enumerate(results, start=1):
            print(f"  {position}. {result.citation}  [{'+'.join(result.sources)}]")

    await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description="Index a repository for retrieval.")
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--url", default=None, help="logical repository URL (defaults to the path)")
    parser.add_argument("--query", default=None, help="run a retrieval query after indexing")
    arguments = parser.parse_args()

    path = arguments.path.expanduser().resolve()
    if not path.is_dir():
        print(f"path does not exist: {path}", file=sys.stderr)
        return 1

    asyncio.run(run(path, arguments.url, arguments.query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
