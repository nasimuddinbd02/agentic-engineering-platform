"""get_dependencies - level 3 retrieval (section 12).

Answers "what does this file depend on, and who depends on it" from imports,
usings and constructor injection.  That neighbourhood is usually where a bug
in a service actually lives.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar

from core.errors import WorkspaceViolationError
from retrieval.ingestion.parser import language_of
from tools.base import Tool, ToolContext, ToolResult
from tools.repository.search_code import iter_source_files

_CSHARP_USING = re.compile(r"^\s*using\s+(?:static\s+)?([A-Za-z_][\w\.]*)\s*;")
_CSHARP_TYPE_REF = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\b")
_PYTHON_IMPORT = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))")
_TS_IMPORT = re.compile(r"""^\s*import\s+.*?from\s+['"]([^'"]+)['"]""")


def _outgoing(content: str, language: str) -> list[str]:
    results: list[str] = []
    for line in content.splitlines():
        if language == "csharp":
            match = _CSHARP_USING.match(line)
            if match:
                results.append(match.group(1))
        elif language == "python":
            match = _PYTHON_IMPORT.match(line)
            if match:
                results.append(match.group(1) or match.group(2))
        elif language in ("typescript", "javascript"):
            match = _TS_IMPORT.match(line)
            if match:
                results.append(match.group(1))
    return sorted(set(results))


def _referenced_types(content: str) -> set[str]:
    return set(_CSHARP_TYPE_REF.findall(content))


class GetDependenciesTool(Tool):
    name = "get_dependencies"
    description = (
        "Show what a file imports and which other files reference the types it declares. "
        "Use it to understand the blast radius of a change before editing."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Repository-relative file path."}},
        "required": ["path"],
        "additionalProperties": False,
    }

    async def run(self, context: ToolContext, *, path: str, **_: Any) -> ToolResult:
        try:
            target = context.resolve(path)
        except WorkspaceViolationError as exc:
            return ToolResult.failure(str(exc))
        if not target.is_file():
            return ToolResult.failure(f"file not found: {path}")

        content = target.read_text(encoding="utf-8", errors="replace")
        language = language_of(path)
        outgoing = _outgoing(content, language)

        from retrieval.ingestion.parser import parse_symbols

        declared = {
            symbol.name
            for symbol in parse_symbols(path, content)
            if symbol.kind in ("class", "interface", "record", "struct", "enum")
        }

        dependents: list[str] = []
        root: Path = context.root
        if declared:
            for candidate in iter_source_files(root):
                relative = candidate.relative_to(root).as_posix()
                if relative == context.relative(target):
                    continue
                try:
                    other = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if declared & _referenced_types(other):
                    dependents.append(relative)

        lines = [f"file: {context.relative(target)}"]
        lines.append("declares: " + (", ".join(sorted(declared)) or "(no types)"))
        lines.append("imports: " + (", ".join(outgoing) or "(none)"))
        lines.append("referenced by: " + (", ".join(sorted(dependents)[:25]) or "(no other file)"))
        return ToolResult.success("\n".join(lines), files=sorted(dependents), imports=outgoing)
