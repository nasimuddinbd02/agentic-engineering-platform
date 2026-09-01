"""read_file - workspace-scoped file read."""

from __future__ import annotations

from typing import Any, ClassVar

from core.errors import WorkspaceViolationError
from tools.base import Tool, ToolContext, ToolResult

MAX_BYTES = 200_000


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read a UTF-8 text file from the task workspace. Paths are relative to the "
        "repository root. Returns the file with 1-based line numbers."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative file path."},
            "start_line": {"type": "integer", "description": "First line to return (1-based)."},
            "end_line": {"type": "integer", "description": "Last line to return, inclusive."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    async def run(
        self,
        context: ToolContext,
        *,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        **_: Any,
    ) -> ToolResult:
        try:
            target = context.resolve(path)
        except WorkspaceViolationError as exc:
            return ToolResult.failure(str(exc))

        if not target.is_file():
            return ToolResult.failure(f"file not found: {path}")
        if target.stat().st_size > MAX_BYTES:
            return ToolResult.failure(
                f"file too large ({target.stat().st_size} bytes); read a line range instead"
            )

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        first = max(1, start_line or 1)
        last = min(len(lines), end_line or len(lines))
        selected = lines[first - 1 : last]
        numbered = "\n".join(f"{first + offset:>5}  {line}" for offset, line in enumerate(selected))
        return ToolResult.success(
            numbered or "(empty selection)",
            path=context.relative(target),
            total_lines=len(lines),
        )
