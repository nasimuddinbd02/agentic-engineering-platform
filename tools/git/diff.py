"""git_diff / git_status - read-only inspection of the worktree."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolContext, ToolResult
from tools.runner import run_command


@dataclass
class DiffSummary:
    diff: str
    files: list[str]
    insertions: int
    deletions: int


async def collect_diff(workspace_path: Path, timeout: int = 120) -> DiffSummary:
    """Diff of everything in the worktree, tracked and untracked alike."""
    # Stage intent-to-add so new files show up in `git diff` without committing.
    await run_command(["git", "add", "--intent-to-add", "--all"], cwd=workspace_path, timeout=timeout)
    diff_result = await run_command(["git", "diff", "HEAD"], cwd=workspace_path, timeout=timeout)
    name_status = await run_command(
        ["git", "diff", "--name-status", "HEAD"], cwd=workspace_path, timeout=timeout
    )
    numstat = await run_command(
        ["git", "diff", "--numstat", "HEAD"], cwd=workspace_path, timeout=timeout
    )

    files: list[str] = []
    for line in name_status.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append(parts[-1].strip())

    insertions = deletions = 0
    for line in numstat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                insertions += int(parts[0])
                deletions += int(parts[1])
            except ValueError:  # binary files report '-'
                continue

    return DiffSummary(
        diff=diff_result.stdout, files=files, insertions=insertions, deletions=deletions
    )


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Show the unified diff of all changes made in this task's workspace."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def run(self, context: ToolContext, **_: Any) -> ToolResult:
        if context.workspace is None:
            return ToolResult.failure("no workspace for this task")
        summary = await collect_diff(context.workspace.path)
        if not summary.files:
            return ToolResult.success("no changes")
        return ToolResult.success(
            summary.diff or "(no textual diff)",
            files=summary.files,
            insertions=summary.insertions,
            deletions=summary.deletions,
        )


class GitStatusTool(Tool):
    name = "git_status"
    description = "List files changed in this task's workspace, without the diff body."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    async def run(self, context: ToolContext, **_: Any) -> ToolResult:
        if context.workspace is None:
            return ToolResult.failure("no workspace for this task")
        result = await run_command(
            ["git", "status", "--porcelain"], cwd=context.workspace.path, timeout=60
        )
        return ToolResult.success(result.stdout or "clean", exit_code=result.exit_code)
