"""Workspace isolation (sections 2.5, 18 and 19).

Every task gets its own Git worktree.  The developer's checkout is never the
agent's working directory, and every path a tool touches is resolved back
inside the workspace before it is opened.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from core.errors import WorkspaceViolationError
from core.logging import get_logger
from tools.runner import CommandResult, run_command

log = get_logger(__name__)

BRANCH_PREFIX = "agent/"


def resolve_inside(root: Path, candidate: str | Path) -> Path:
    """Resolve ``candidate`` and refuse anything that escapes ``root``.

    Blocks ``../`` traversal, absolute paths pointing elsewhere, and symlinks
    that leave the tree.
    """
    root = root.resolve()
    raw = Path(candidate)
    target = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if target != root and root not in target.parents:
        raise WorkspaceViolationError(f"path escapes workspace: {candidate}")
    return target


@dataclass
class Workspace:
    task_id: str
    path: Path
    branch: str
    repository_path: Path

    def resolve(self, relative: str | Path) -> Path:
        return resolve_inside(self.path, relative)

    def relative(self, absolute: Path) -> str:
        return absolute.resolve().relative_to(self.path.resolve()).as_posix()


class WorkspaceManager:
    """Creates and destroys per-task Git worktrees."""

    def __init__(self, workspace_root: Path, command_timeout: int = 600) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.command_timeout = command_timeout
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._active: dict[str, Workspace] = {}

    def get(self, task_id: str) -> Workspace:
        workspace = self._active.get(task_id)
        if workspace is None:
            raise WorkspaceViolationError(f"no workspace for task {task_id}")
        return workspace

    def try_get(self, task_id: str) -> Workspace | None:
        return self._active.get(task_id)

    async def create(self, task_id: str, repository_path: Path) -> Workspace:
        """``git worktree add ../workspaces/TASK-x -b agent/TASK-x`` (section 18)."""
        repository_path = Path(repository_path).expanduser().resolve()
        if not (repository_path / ".git").exists():
            raise WorkspaceViolationError(f"not a git repository: {repository_path}")

        target = self.workspace_root / task_id
        branch = f"{BRANCH_PREFIX}{task_id}"
        if target.exists():
            await self._remove_worktree(repository_path, target, branch)

        result = await run_command(
            ["git", "worktree", "add", str(target), "-b", branch],
            cwd=repository_path,
            timeout=self.command_timeout,
        )
        if result.exit_code != 0:
            raise WorkspaceViolationError(
                f"git worktree add failed ({result.exit_code}): {result.stderr.strip()}"
            )

        workspace = Workspace(
            task_id=task_id, path=target, branch=branch, repository_path=repository_path
        )
        self._active[task_id] = workspace
        log.info("workspace.created", task_id=task_id, path=str(target), branch=branch)
        return workspace

    async def adopt(
        self, task_id: str, path: Path, branch: str, repository_path: Path
    ) -> Workspace:
        """Re-register an existing workspace after a worker restart (section 55)."""
        workspace = Workspace(
            task_id=task_id,
            path=Path(path).resolve(),
            branch=branch,
            repository_path=Path(repository_path).resolve(),
        )
        self._active[task_id] = workspace
        return workspace

    async def destroy(self, task_id: str, *, keep_branch: bool = True) -> None:
        workspace = self._active.pop(task_id, None)
        if workspace is None:
            return
        await self._remove_worktree(
            workspace.repository_path,
            workspace.path,
            None if keep_branch else workspace.branch,
        )
        log.info("workspace.destroyed", task_id=task_id)

    async def _remove_worktree(
        self, repository_path: Path, target: Path, branch: str | None
    ) -> CommandResult | None:
        result = await run_command(
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=repository_path,
            timeout=self.command_timeout,
        )
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        await run_command(["git", "worktree", "prune"], cwd=repository_path, timeout=60)
        if branch:
            await run_command(["git", "branch", "-D", branch], cwd=repository_path, timeout=60)
        return result
