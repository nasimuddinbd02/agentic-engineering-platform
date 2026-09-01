"""Repository scanning - which files are worth indexing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from retrieval.ingestion.parser import language_of

SKIP_DIRECTORIES = {
    ".git",
    "bin",
    "obj",
    "node_modules",
    ".vs",
    ".idea",
    "__pycache__",
    ".next",
    "dist",
    "build",
    "packages",
    ".venv",
    "venv",
    "TestResults",
}
INDEXABLE_SUFFIXES = {".cs", ".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".md"}
MAX_FILE_BYTES = 1_000_000


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    relative_path: str
    language: str
    content: str


def scan_repository(root: Path) -> list[ScannedFile]:
    root = Path(root).resolve()
    files: list[ScannedFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() not in INDEXABLE_SUFFIXES:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        files.append(
            ScannedFile(
                path=path,
                relative_path=relative,
                language=language_of(relative),
                content=content,
            )
        )
    return files


def detect_languages(files: list[ScannedFile]) -> list[str]:
    return sorted({file.language for file in files if file.language != "text"})
