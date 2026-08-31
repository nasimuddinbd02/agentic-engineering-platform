"""list_directory - workspace-scoped directory listing."""

from __future__ import annotations

from typing import Any

from core.errors import WorkspaceViolationError
from tools.base import Tool, ToolContext, ToolResult

IGNORED = {".git", "bin", "obj", "node_modules", ".vs", ".idea", "__pycache__", ".next"}
MAX_ENTRIES = 300


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = (
        "List files and folders under a repository-relative directory. "
        "Build output and VCS internals are omitted."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative directory, '.' for root."},
            "recursive": {"type": "boolean", "description": "Walk subdirectories."},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    async def run(
        self, context: ToolContext, *, path: str = ".", recursive: bool = False, **_: Any
    ) -> ToolResult:
        try:
            target = context.resolve(path or ".")
        except WorkspaceViolationError as exc:
            return ToolResult.failure(str(exc))
        if not target.is_dir():
            return ToolResult.failure(f"not a directory: {path}")

        entries: list[str] = []
        iterator = target.rglob("*") if recursive else target.iterdir()
        for entry in sorted(iterator):
            if any(part in IGNORED for part in entry.parts):
                continue
            relative = context.relative(entry)
            entries.append(f"{relative}/" if entry.is_dir() else relative)
            if len(entries) >= MAX_ENTRIES:
                entries.append(f"... truncated at {MAX_ENTRIES} entries")
                break

        return ToolResult.success("\n".join(entries) or "(empty)", count=len(entries))
