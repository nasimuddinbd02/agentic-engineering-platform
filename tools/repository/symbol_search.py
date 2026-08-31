"""find_symbol / find_references - level 2 retrieval (section 12).

A regex symbol index rather than a full parser: enough to answer "where is
OrderService defined and who calls CancelOrder" for C#, Python and TypeScript,
with no language server to install.  :mod:`retrieval.ingestion.parser` shares
these patterns so search and RAG chunking agree on what a symbol is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from retrieval.ingestion.parser import Symbol, parse_symbols
from tools.base import Tool, ToolContext, ToolResult
from tools.repository.search_code import iter_source_files, search_python

MAX_RESULTS = 40


def index_symbols(root: Path) -> list[Symbol]:
    symbols: list[Symbol] = []
    for path in iter_source_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        symbols.extend(parse_symbols(relative, content))
    return symbols


class FindSymbolTool(Tool):
    name = "find_symbol"
    description = (
        "Find where a class, interface, record, method or function is DEFINED. "
        "Use this after search_code to jump straight to a definition."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol name, e.g. 'OrderService'."}
        },
        "required": ["symbol"],
        "additionalProperties": False,
    }

    async def run(self, context: ToolContext, *, symbol: str, **_: Any) -> ToolResult:
        needle = symbol.strip()
        hits = [
            found
            for found in index_symbols(context.root)
            if found.name.lower() == needle.lower()
        ]
        if not hits:
            partial = [
                found
                for found in index_symbols(context.root)
                if needle.lower() in found.name.lower()
            ][:MAX_RESULTS]
            if not partial:
                return ToolResult.success(f"no definition found for '{symbol}'")
            body = "\n".join(
                f"{hit.file_path}:{hit.start_line}: {hit.kind} {hit.name} (partial match)"
                for hit in partial
            )
            return ToolResult.success(body, files=sorted({hit.file_path for hit in partial}))

        body = "\n".join(
            f"{hit.file_path}:{hit.start_line}-{hit.end_line}: {hit.kind} {hit.name}"
            for hit in hits[:MAX_RESULTS]
        )
        return ToolResult.success(body, files=sorted({hit.file_path for hit in hits}))


class FindReferencesTool(Tool):
    name = "find_references"
    description = "Find call sites and other references to a symbol across the repository."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Symbol name to look for."}
        },
        "required": ["symbol"],
        "additionalProperties": False,
    }

    async def run(self, context: ToolContext, *, symbol: str, **_: Any) -> ToolResult:
        needle = symbol.strip()
        if not needle.isidentifier():
            return ToolResult.failure("symbol must be a plain identifier")
        matches = search_python(context.root, rf"\b{needle}\b", limit=MAX_RESULTS)
        definitions = {
            found.file_path
            for found in index_symbols(context.root)
            if found.name.lower() == needle.lower()
        }
        references = [match for match in matches if match.path not in definitions] or matches
        if not references:
            return ToolResult.success(f"no references to '{symbol}'")
        body = "\n".join(match.render() for match in references)
        return ToolResult.success(
            body, files=sorted({match.path for match in references}), count=len(references)
        )
