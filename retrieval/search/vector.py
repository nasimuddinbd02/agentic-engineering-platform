"""Vector search - level 4 of section 12.

The interface is here so hybrid retrieval can be wired end to end; it stays
switched off until an embedder is configured, exactly as section 12 instructs
("do not begin with vector search").

Storage note: ``code_chunks.embedding`` is JSON in the POC so the ORM is
identical on SQLite and PostgreSQL, and similarity is computed in Python.  On
PostgreSQL, phase 9 swaps that column to ``vector(N)`` with pgvector and moves
the ORDER BY into SQL - see persistence/migrations/0002_pgvector.sql.  Nothing
above this module changes when that happens.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod

from persistence.models import CodeChunk
from retrieval.search.lexical import ScoredChunk


class Embedder(ABC):
    """Produces embeddings for chunk text and for queries."""

    dimensions: int = 0

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


class VectorIndex:
    def __init__(self, chunks: list[CodeChunk]) -> None:
        self.chunks = [chunk for chunk in chunks if chunk.embedding]

    @property
    def enabled(self) -> bool:
        return bool(self.chunks)

    def search(self, query_embedding: list[float], limit: int = 10) -> list[ScoredChunk]:
        scored = [
            ScoredChunk(chunk, cosine_similarity(query_embedding, chunk.embedding or []), "vector")
            for chunk in self.chunks
        ]
        scored = [item for item in scored if item.score > 0]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]
