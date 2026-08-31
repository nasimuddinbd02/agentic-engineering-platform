"""Lexical scoring over indexed chunks - level 1/2 of section 12, database side.

BM25-ish term weighting: cheap, explainable, and a strong baseline that a vector
index has to beat rather than replace.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from persistence.models import CodeChunk

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

K1 = 1.5
B = 0.75


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text):
        lowered = raw.lower()
        tokens.append(lowered)
        # Split CamelCase so "CancelOrder" also matches "cancel" and "order".
        parts = [part.lower() for part in _CAMEL.split(raw) if len(part) > 2]
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens


@dataclass
class ScoredChunk:
    chunk: CodeChunk
    score: float
    source: str = "lexical"


class LexicalIndex:
    """In-memory BM25 over one repository's chunks."""

    def __init__(self, chunks: list[CodeChunk]) -> None:
        self.chunks = chunks
        self.documents = [tokenize(f"{c.file_path} {c.symbol_name or ''} {c.content}") for c in chunks]
        self.frequencies = [Counter(document) for document in self.documents]
        self.lengths = [len(document) for document in self.documents]
        self.average_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.document_frequency: Counter[str] = Counter()
        for frequency in self.frequencies:
            self.document_frequency.update(frequency.keys())

    def search(self, query: str, limit: int = 10) -> list[ScoredChunk]:
        terms = tokenize(query)
        if not terms or not self.chunks:
            return []
        total = len(self.chunks)
        results: list[ScoredChunk] = []
        for index, frequency in enumerate(self.frequencies):
            score = 0.0
            for term in terms:
                occurrences = frequency.get(term, 0)
                if not occurrences:
                    continue
                appearances = self.document_frequency[term]
                idf = math.log(1 + (total - appearances + 0.5) / (appearances + 0.5))
                length_norm = 1 - B + B * (self.lengths[index] / (self.average_length or 1))
                score += idf * (occurrences * (K1 + 1)) / (occurrences + K1 * length_norm)
            if score > 0:
                results.append(ScoredChunk(self.chunks[index], score))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]
