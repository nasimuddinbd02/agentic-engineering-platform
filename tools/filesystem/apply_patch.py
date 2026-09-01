"""apply_patch / create_file - the only tools that change source files.

Edits are exact search-and-replace against a unique anchor rather than unified
diff hunks: an anchor that does not match, or matches twice, fails loudly
instead of corrupting the file.  Line offsets drift between iterations of the
debugging loop; anchors do not.
"""

from __future__ import annotations

from typing import Any, ClassVar

from core.errors import WorkspaceViolationError
from tools.base import Tool, ToolContext, ToolResult


def _count_changes(before: str, after: str) -> tuple[int, int]:
    import difflib

    added = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "Replace an exact block of text in a file. old_text must appear exactly once "
        "in the file, including indentation. Use create_file for new files."
    )
    mutating = True
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative file path."},
            "old_text": {
                "type": "string",
                "description": "Exact existing text to replace, including indentation.",
            },
            "new_text": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }

    async def run(
        self,
        context: ToolContext,
        *,
        path: str,
        old_text: str,
        new_text: str,
        **_: Any,
    ) -> ToolResult:
        if not context.write_allowed:
            return ToolResult.failure("writes are not permitted for this task (policy)")
        try:
            target = context.resolve(path)
        except WorkspaceViolationError as exc:
            return ToolResult.failure(str(exc))
        if not target.is_file():
            return ToolResult.failure(f"file not found: {path}")
        if old_text == new_text:
            return ToolResult.failure("old_text and new_text are identical - nothing to do")

        original = target.read_text(encoding="utf-8")
        occurrences = original.count(old_text)
        if occurrences == 0:
            return ToolResult.failure(
                f"old_text not found in {path}. Read the file again and copy the exact text."
            )
        if occurrences > 1:
            return ToolResult.failure(
                f"old_text appears {occurrences} times in {path}; include more surrounding "
                "context so the anchor is unique."
            )

        updated = original.replace(old_text, new_text, 1)
        target.write_text(updated, encoding="utf-8", newline="")
        added, removed = _count_changes(original, updated)
        relative = context.relative(target)
        return ToolResult.success(
            f"patched {relative} (+{added}/-{removed})",
            path=relative,
            change_type="MODIFIED",
            lines_added=added,
            lines_removed=removed,
        )


class CreateFileTool(Tool):
    name = "create_file"
    description = (
        "Create a new file with the given content. Fails if the file already exists - "
        "use apply_patch to modify an existing file."
    )
    mutating = True
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository-relative file path."},
            "content": {"type": "string", "description": "Full file content."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    async def run(self, context: ToolContext, *, path: str, content: str, **_: Any) -> ToolResult:
        if not context.write_allowed:
            return ToolResult.failure("writes are not permitted for this task (policy)")
        try:
            target = context.resolve(path)
        except WorkspaceViolationError as exc:
            return ToolResult.failure(str(exc))
        if target.exists():
            return ToolResult.failure(f"{path} already exists - use apply_patch")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        relative = context.relative(target)
        return ToolResult.success(
            f"created {relative} ({len(content.splitlines())} lines)",
            path=relative,
            change_type="ADDED",
            lines_added=len(content.splitlines()),
            lines_removed=0,
        )
