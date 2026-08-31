"""Bootstrap the local POC.

Creates the database schema and materialises the sample .NET repository as a
*separate* Git repository outside the agent's own working tree, because the
agent must never operate on the checkout it lives in (sections 2.5 and 3).

    python -m scripts.bootstrap
    python -m scripts.bootstrap --target D:/Projects/order-service
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from scripts._fs import force_rmtree

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPOSITORY_ROOT / "sample-repo" / "order-service"
DEFAULT_TARGET = REPOSITORY_ROOT / ".sandbox" / "order-service"
IGNORED = shutil.ignore_patterns("bin", "obj", ".git", "TestResults", "*.user")


def _git(arguments: list[str], cwd: Path) -> None:
    result = subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(arguments)} failed:\n{result.stderr}")


def materialize_sample_repository(target: Path, *, force: bool = False) -> Path:
    target = target.expanduser().resolve()
    if target.exists():
        if not force:
            print(f"sample repository already present at {target} (use --force to recreate)")
            return target
        force_rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, target, ignore=IGNORED)
    (target / ".gitignore").write_text("bin/\nobj/\nTestResults/\n", encoding="utf-8")

    _git(["init", "-b", "main"], target)
    _git(["config", "user.name", "POC Bootstrap"], target)
    _git(["config", "user.email", "bootstrap@localhost"], target)
    _git(["add", "--all"], target)
    _git(
        ["commit", "-m", "Initial commit: order service with duplicate-cancellation defect"],
        target,
    )
    print(f"sample repository created at {target}")
    return target


async def prepare_database() -> None:
    from core.config import get_settings
    from persistence.db import create_schema, dispose_engine

    settings = get_settings()
    await create_schema(settings)
    print(f"database schema ready ({settings.database_url.split('://', 1)[0]})")
    await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the local POC environment.")
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="where to create the sample repository checkout",
    )
    parser.add_argument("--force", action="store_true", help="recreate the sample repository")
    parser.add_argument("--skip-database", action="store_true")
    arguments = parser.parse_args()

    sys.path.insert(0, str(REPOSITORY_ROOT))
    target = materialize_sample_repository(arguments.target, force=arguments.force)

    if not arguments.skip_database:
        asyncio.run(prepare_database())

    print("\nNext:")
    print("  1. terminal 1:  python -m apps.worker.main")
    print("  2. terminal 2:  uvicorn apps.api.main:app --port 8000")
    print("  3. terminal 3:  python -m scripts.submit_task \\")
    print(f'                    --repository-path "{target}" \\')
    print('                    --issue "Cancelling an already cancelled order returns HTTP 500."')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
