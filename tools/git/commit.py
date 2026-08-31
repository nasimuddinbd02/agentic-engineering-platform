"""Commit helpers.

Committing is a workflow step performed by the git node, not a capability the
implementation agent can invoke on its own - so these are plain functions, not
tools exposed to a model.
"""

from __future__ import annotations

from pathlib import Path

from core.errors import AgentPlatformError
from core.logging import get_logger
from tools.runner import run_command

log = get_logger(__name__)

AGENT_NAME = "AI Engineering Agent"
AGENT_EMAIL = "agent@localhost"


async def commit_all(workspace_path: Path, message: str, timeout: int = 180) -> str:
    """Stage everything in the worktree and commit. Returns the commit SHA."""
    add = await run_command(["git", "add", "--all"], cwd=workspace_path, timeout=timeout)
    if add.exit_code != 0:
        raise AgentPlatformError(f"git add failed: {add.stderr.strip()}")

    staged = await run_command(
        ["git", "diff", "--cached", "--name-only"], cwd=workspace_path, timeout=timeout
    )
    if not staged.stdout.strip():
        raise AgentPlatformError("nothing to commit")

    commit = await run_command(
        [
            "git",
            "-c",
            f"user.name={AGENT_NAME}",
            "-c",
            f"user.email={AGENT_EMAIL}",
            "commit",
            "-m",
            message,
        ],
        cwd=workspace_path,
        timeout=timeout,
    )
    if commit.exit_code != 0:
        raise AgentPlatformError(f"git commit failed: {commit.combined_output.strip()}")

    sha = await run_command(["git", "rev-parse", "HEAD"], cwd=workspace_path, timeout=60)
    commit_sha = sha.stdout.strip()
    log.info("git.committed", sha=commit_sha, files=len(staged.stdout.strip().splitlines()))
    return commit_sha


async def current_branch(workspace_path: Path) -> str:
    result = await run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace_path, timeout=60
    )
    return result.stdout.strip()


async def changed_files(workspace_path: Path) -> list[str]:
    result = await run_command(
        ["git", "diff", "--name-only", "HEAD"], cwd=workspace_path, timeout=60
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
