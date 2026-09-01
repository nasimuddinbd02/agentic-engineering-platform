"""Shared fixtures.

Every test runs against SQLite and the in-process coordination adapters, so the
suite needs no Docker.  The adapters are the same interfaces the Redis and
PostgreSQL implementations satisfy.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from core.config import Settings  # noqa: E402
from graph.context import WorkflowContext  # noqa: E402
from infrastructure import build_coordination, reset_coordination  # noqa: E402
from llm.scripted_provider import ScriptedLLMProvider  # noqa: E402
from persistence.db import (  # noqa: E402
    create_schema,
    dispose_engine,
    session_scope,
)
from persistence.repositories import TaskRepository  # noqa: E402
from policies.evaluator import PolicyEngine  # noqa: E402
from providers.ci.noop import NoopCIProvider  # noqa: E402
from providers.scm.local import LocalGitProvider  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402
from tools.workspace import WorkspaceManager  # noqa: E402

SAMPLE_TEMPLATE = REPOSITORY_ROOT / "sample-repo" / "order-service"
IGNORED = shutil.ignore_patterns("bin", "obj", ".git", "TestResults")


def dotnet_available() -> bool:
    return shutil.which("dotnet") is not None


requires_dotnet = pytest.mark.skipif(
    not dotnet_available(), reason="the .NET SDK is not installed on this machine"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        redis_url="memory://",
        llm_provider="scripted",
        scm_provider="local",
        ci_provider="none",
        workspace_root=tmp_path / "workspaces",
        artifact_root=tmp_path / "artifacts",
        max_agent_iterations=3,
        max_ci_iterations=2,
        command_timeout_seconds=900,
        log_level="WARNING",
    )


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Settings]:
    await create_schema(settings)
    yield settings
    await dispose_engine()


@pytest.fixture
async def coordination(settings: Settings) -> AsyncIterator[object]:
    await reset_coordination()
    yield build_coordination(settings, consumer_name="test")
    await reset_coordination()


@pytest.fixture
def sample_repository(tmp_path: Path) -> Path:
    """A throwaway git repository containing the sample .NET service."""
    target = tmp_path / "order-service"
    shutil.copytree(SAMPLE_TEMPLATE, target, ignore=IGNORED)
    (target / ".gitignore").write_text("bin/\nobj/\nTestResults/\n", encoding="utf-8")

    def git(*arguments: str) -> None:
        result = subprocess.run(
            ["git", *arguments], cwd=target, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@localhost")
    git("add", "--all")
    git("commit", "-m", "seed")
    return target


@pytest.fixture
def scripted_llm() -> ScriptedLLMProvider:
    return ScriptedLLMProvider()


@pytest.fixture
def workflow_context(
    settings: Settings, scripted_llm: ScriptedLLMProvider, coordination
) -> WorkflowContext:
    return WorkflowContext(
        settings=settings,
        llm=scripted_llm,
        tools=ToolRegistry(settings),
        workspaces=WorkspaceManager(settings.workspace_root, settings.command_timeout_seconds),
        policy=PolicyEngine.from_file(),
        scm=LocalGitProvider(settings.artifact_root),
        ci=NoopCIProvider(),
        events=coordination.events,
        task_id="TASK-test",
        workflow_run_id="run-test",
        prompts_path=REPOSITORY_ROOT / "prompts",
    )


@pytest.fixture
async def seeded_task(database: Settings, sample_repository: Path):
    """A QUEUED task row pointing at the throwaway repository."""
    async with session_scope(database) as session:
        task = await TaskRepository(session).create(
            repository_url="file://order-service",
            repository_path=str(sample_repository),
            issue=(
                "Cancelling an order that is already cancelled returns HTTP 500 "
                "instead of succeeding. Make cancellation idempotent and add a "
                "regression test."
            ),
        )
        return task.id
