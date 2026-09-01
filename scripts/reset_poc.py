"""Reset the local POC to a clean state.

    python -m scripts.reset_poc            # drop tables, clear workspaces
    python -m scripts.reset_poc --all      # also recreate the sample repository

Removing a workspace also removes the worktree registration in the sample
repository, so this never leaves orphaned ``git worktree`` entries behind.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from scripts._fs import force_rmtree

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))


def clear_directory(path: Path, label: str) -> None:
    if path.is_dir():
        force_rmtree(path)
        print(f"removed {label}: {path}")
    path.mkdir(parents=True, exist_ok=True)


def prune_worktrees(repository: Path) -> None:
    if not (repository / ".git").exists():
        return
    subprocess.run(["git", "worktree", "prune"], cwd=repository, capture_output=True, check=False)
    listing = subprocess.run(
        ["git", "branch", "--list", "agent/*", "--format=%(refname:short)"],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    for branch in listing.stdout.split():
        subprocess.run(
            ["git", "branch", "-D", branch], cwd=repository, capture_output=True, check=False
        )
        print(f"deleted branch {branch} in {repository.name}")


async def drop_tables() -> None:
    from core.config import get_settings
    from persistence.db import create_schema, dispose_engine, drop_schema

    settings = get_settings()
    await drop_schema(settings)
    await create_schema(settings)
    print("database schema recreated")
    await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the local POC.")
    parser.add_argument("--all", action="store_true", help="also recreate the sample repository")
    parser.add_argument("--keep-database", action="store_true")
    arguments = parser.parse_args()

    from core.config import get_settings

    settings = get_settings()

    sandbox = REPOSITORY_ROOT / ".sandbox" / "order-service"
    prune_worktrees(sandbox)

    clear_directory(Path(settings.workspace_root), "workspaces")
    clear_directory(Path(settings.artifact_root), "artifacts")

    if not arguments.keep_database:
        asyncio.run(drop_tables())

    if arguments.all:
        from scripts.bootstrap import materialize_sample_repository

        materialize_sample_repository(sandbox, force=True)

    print("reset complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
