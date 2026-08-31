"""Chunking.

Symbol-aligned rather than fixed-window: a chunk is a class or a method, so a
retrieved chunk is something a reviewer would recognise.  Files with no
extractable symbols fall back to bounded line windows.
"""

from __future__ import annotations

from dataclasses import dataclass

from retrieval.ingestion.parser import Symbol, parse_symbols
from retrieval.ingestion.scanner import ScannedFile

MAX_CHUNK_LINES = 160
WINDOW_LINES = 80
WINDOW_OVERLAP = 15


@dataclass
class Chunk:
    file_path: str
    language: str
    content: str
    start_line: int
    end_line: int
    symbol_name: str | None = None
    symbol_kind: str | None = None


def _slice(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : end])


def chunk_file(file: ScannedFile) -> list[Chunk]:
    lines = file.content.splitlines()
    if not lines:
        return []

    symbols: list[Symbol] = parse_symbols(file.relative_path, file.content)
    # Keep only top-level-ish symbols; a method inside an indexed class is fine
    # to index twice, but a 3000-line class is not a useful chunk.
    usable = [
        symbol
        for symbol in symbols
        if symbol.end_line >= symbol.start_line
        and (symbol.end_line - symbol.start_line) <= MAX_CHUNK_LINES
    ]

    if not usable:
        return _window_chunks(file, lines)

    chunks = [
        Chunk(
            file_path=file.relative_path,
            language=file.language,
            content=_slice(lines, symbol.start_line, symbol.end_line),
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            symbol_name=symbol.name,
            symbol_kind=symbol.kind,
        )
        for symbol in usable
    ]
    return [chunk for chunk in chunks if chunk.content.strip()]


def _window_chunks(file: ScannedFile, lines: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    start = 1
    while start <= len(lines):
        end = min(len(lines), start + WINDOW_LINES - 1)
        body = _slice(lines, start, end)
        if body.strip():
            chunks.append(
                Chunk(
                    file_path=file.relative_path,
                    language=file.language,
                    content=body,
                    start_line=start,
                    end_line=end,
                )
            )
        if end == len(lines):
            break
        start = end - WINDOW_OVERLAP + 1
    return chunks
