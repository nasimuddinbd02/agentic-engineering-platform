"""Language-aware symbol extraction.

Shared by the symbol-search tool (level 2 retrieval) and by the RAG chunker, so
"what is a symbol" has exactly one definition in the platform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LANGUAGE_BY_SUFFIX = {
    ".cs": "csharp",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".sql": "sql",
    ".md": "markdown",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
}


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    language: str


_CSHARP_TYPE = re.compile(
    r"^\s*(?:public|internal|private|protected|sealed|static|abstract|partial|\s)*"
    r"\b(?P<kind>class|interface|record|struct|enum)\s+(?P<name>[A-Za-z_]\w*)"
)
_CSHARP_MEMBER = re.compile(
    r"^\s*(?:public|internal|private|protected|static|async|virtual|override|sealed|\s)+"
    r"(?:[A-Za-z_][\w<>,\[\]\.\?]*\s+)+(?P<name>[A-Za-z_]\w*)\s*\("
)
_PYTHON_DEF = re.compile(r"^\s*(?P<kind>class|def)\s+(?P<name>[A-Za-z_]\w*)")
_TS_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?P<kind>class|interface|type|function|const)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
)

_CSHARP_KEYWORDS = {"if", "for", "foreach", "while", "switch", "catch", "using", "lock", "return"}


def language_of(file_path: str) -> str:
    suffix = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    return LANGUAGE_BY_SUFFIX.get(suffix, "text")


def parse_symbols(file_path: str, content: str) -> list[Symbol]:
    language = language_of(file_path)
    lines = content.splitlines()
    if language == "csharp":
        return _parse_csharp(file_path, lines)
    if language == "python":
        return _parse_python(file_path, lines)
    if language in ("typescript", "javascript"):
        return _parse_braced(file_path, lines, _TS_DEF, language)
    return []


def _block_end(lines: list[str], start_index: int) -> int:
    """End line of a brace-delimited block starting at or after ``start_index``."""
    depth = 0
    opened = False
    for offset in range(start_index, len(lines)):
        for character in lines[offset]:
            if character == "{":
                depth += 1
                opened = True
            elif character == "}":
                depth -= 1
                if opened and depth == 0:
                    return offset + 1
        if opened and depth == 0:
            return offset + 1
    return len(lines)


def _parse_csharp(file_path: str, lines: list[str]) -> list[Symbol]:
    symbols: list[Symbol] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        type_match = _CSHARP_TYPE.match(line)
        if type_match:
            symbols.append(
                Symbol(
                    name=type_match.group("name"),
                    kind=type_match.group("kind"),
                    file_path=file_path,
                    start_line=index + 1,
                    end_line=_block_end(lines, index),
                    language="csharp",
                )
            )
            continue
        member_match = _CSHARP_MEMBER.match(line)
        if member_match and member_match.group("name") not in _CSHARP_KEYWORDS:
            symbols.append(
                Symbol(
                    name=member_match.group("name"),
                    kind="method",
                    file_path=file_path,
                    start_line=index + 1,
                    end_line=_block_end(lines, index),
                    language="csharp",
                )
            )
    return symbols


def _parse_python(file_path: str, lines: list[str]) -> list[Symbol]:
    symbols: list[Symbol] = []
    for index, line in enumerate(lines):
        match = _PYTHON_DEF.match(line)
        if not match:
            continue
        indent = len(line) - len(line.lstrip())
        end = len(lines)
        for offset in range(index + 1, len(lines)):
            candidate = lines[offset]
            if candidate.strip() and (len(candidate) - len(candidate.lstrip())) <= indent:
                end = offset
                break
        symbols.append(
            Symbol(
                name=match.group("name"),
                kind="class" if match.group("kind") == "class" else "function",
                file_path=file_path,
                start_line=index + 1,
                end_line=end,
                language="python",
            )
        )
    return symbols


def _parse_braced(
    file_path: str, lines: list[str], pattern: re.Pattern[str], language: str
) -> list[Symbol]:
    symbols: list[Symbol] = []
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        symbols.append(
            Symbol(
                name=match.group("name"),
                kind=match.group("kind"),
                file_path=file_path,
                start_line=index + 1,
                end_line=_block_end(lines, index),
                language=language,
            )
        )
    return symbols
