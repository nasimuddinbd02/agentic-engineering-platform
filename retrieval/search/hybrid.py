"""Hybrid retrieval and reranking - level 5 of section 12.

    issue -> keyword + symbol + dependency (+ vector when enabled)
          -> candidate set -> reranker -> final context

Fusion is reciprocal rank fusion, so scores from different scales can be
combined without tuning weights per corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

from persistence.models import CodeChunk
from retrieval.search.lexical import LexicalIndex, ScoredChunk, tokenize
from retrieval.search.reranker import rerank
from retrieval.search.vector import Embedder, VectorIndex

RRF_K = 60


@dataclass
class RetrievalResult:
    chunk: CodeChunk
    score: float
    sources: list[str]

    @property
    def citation(self) -> str:
        location = f"{self.chunk.file_path}:{self.chunk.start_line}-{self.chunk.end_line}"
        return f"{location} ({self.chunk.symbol_name or 'block'})"


class HybridRetriever:
    def __init__(self, chunks: list[CodeChunk], embedder: Embedder | None = None) -> None:
        self.chunks = chunks
        self.lexical = LexicalIndex(chunks)
        self.vector = VectorIndex(chunks)
        self.embedder = embedder

    def symbol_search(self, query: str, limit: int = 10) -> list[ScoredChunk]:
        terms = set(tokenize(query))
        hits = [
            ScoredChunk(chunk, 1.0, "symbol")
            for chunk in self.chunks
            if chunk.symbol_name and chunk.symbol_name.lower() in terms
        ]
        return hits[:limit]

    async def search(self, query: str, limit: int = 8) -> list[RetrievalResult]:
        ranked_lists: list[list[ScoredChunk]] = [
            self.lexical.search(query, limit=limit * 3),
            self.symbol_search(query, limit=limit * 2),
        ]
        if self.embedder is not None and self.vector.enabled:
            embedding = await self.embedder.embed_query(query)
            ranked_lists.append(self.vector.search(embedding, limit=limit * 3))

        fused: dict[str, tuple[CodeChunk, float, list[str]]] = {}
        for ranked in ranked_lists:
            for position, item in enumerate(ranked, start=1):
                key = item.chunk.id
                contribution = 1.0 / (RRF_K + position)
                if key in fused:
                    chunk, score, sources = fused[key]
                    fused[key] = (chunk, score + contribution, [*sources, item.source])
                else:
                    fused[key] = (item.chunk, contribution, [item.source])

        candidates = [
            RetrievalResult(chunk=chunk, score=score, sources=sorted(set(sources)))
            for chunk, score, sources in fused.values()
        ]
        candidates.sort(key=lambda item: item.score, reverse=True)
        return rerank(query, candidates[: limit * 3])[:limit]
