"""Reranking (section 12, level 5).

A deterministic feature-based reranker rather than a cross-encoder: it is fast,
free, needs no model download, and encodes what actually matters when ranking
code for a bug fix.  Swapping in a cross-encoder later means replacing this one
function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from retrieval.search.lexical import tokenize

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters for typing
    from retrieval.search.hybrid import RetrievalResult

#: Files whose name says "test" are usually context, not the site of the defect.
TEST_MARKERS = ("test", "spec", "fixture")
#: Service and handler layers are where behaviour lives.
BEHAVIOUR_MARKERS = ("service", "controller", "handler", "repository", "manager")


def _feature_score(query_terms: set[str], result: RetrievalResult) -> float:
    chunk = result.chunk
    path = chunk.file_path.lower()
    score = 0.0

    if chunk.symbol_name and chunk.symbol_name.lower() in query_terms:
        score += 2.0
    if any(term in path for term in query_terms):
        score += 1.0
    if any(marker in path for marker in BEHAVIOUR_MARKERS):
        score += 0.5
    if any(marker in path for marker in TEST_MARKERS):
        score -= 0.4
    if chunk.symbol_kind in ("method", "function"):
        score += 0.3

    body = chunk.content.lower()
    overlap = sum(1 for term in query_terms if term in body)
    score += min(overlap, 6) * 0.15

    # Very small chunks rarely carry enough context to act on.
    if (chunk.end_line - chunk.start_line) < 3:
        score -= 0.3
    return score


def rerank(query: str, candidates: list[RetrievalResult]) -> list[RetrievalResult]:
    terms = set(tokenize(query))
    if not candidates:
        return []
    highest = max(candidate.score for candidate in candidates) or 1.0
    for candidate in candidates:
        normalized = candidate.score / highest
        candidate.score = normalized + _feature_score(terms, candidate)
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates
