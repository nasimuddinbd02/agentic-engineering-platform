"""Workspace boundary tests (section 19) and command allowlisting (section 20).

Path traversal and arbitrary command execution are the two ways an agent
escapes its sandbox, so both are tested directly rather than through the graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.errors import WorkspaceViolationError
from tools.runner import ALLOWED_EXECUTABLES, run_command
from tools.workspace import resolve_inside


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "file.cs").write_text("class A {}", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return root


def test_relative_path_resolves_inside(workspace: Path) -> None:
    assert resolve_inside(workspace, "src/file.cs").is_file()


@pytest.mark.parametrize(
    "candidate",
    [
        "../outside.txt",
        "../../outside.txt",
        "src/../../outside.txt",
        "src/../../../Windows/System32/config",
        "./../outside.txt",
    ],
)
def test_traversal_is_refused(workspace: Path, candidate: str) -> None:
    with pytest.raises(WorkspaceViolationError):
        resolve_inside(workspace, candidate)


def test_absolute_path_outside_is_refused(workspace: Path, tmp_path: Path) -> None:
    with pytest.raises(WorkspaceViolationError):
        resolve_inside(workspace, str(tmp_path / "outside.txt"))


def test_absolute_path_inside_is_allowed(workspace: Path) -> None:
    assert resolve_inside(workspace, str(workspace / "src" / "file.cs")).is_file()


def test_workspace_root_itself_is_allowed(workspace: Path) -> None:
    assert resolve_inside(workspace, ".") == workspace.resolve()


async def test_disallowed_executable_is_refused(tmp_path: Path) -> None:
    for command in (["curl", "http://example.com"], ["powershell", "-c", "ls"], ["rm", "-rf", "/"]):
        with pytest.raises(WorkspaceViolationError):
            await run_command(command, cwd=tmp_path)


async def test_empty_command_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceViolationError):
        await run_command([], cwd=tmp_path)


async def test_missing_working_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceViolationError):
        await run_command(["git", "status"], cwd=tmp_path / "nope")


async def test_allowed_command_runs_and_is_measured(tmp_path: Path) -> None:
    result = await run_command(["git", "--version"], cwd=tmp_path, timeout=60)
    assert result.exit_code == 0
    assert "git version" in result.stdout
    assert result.duration_ms >= 0
    assert not result.timed_out


def test_allowlist_contains_no_shell() -> None:
    """A shell would make every other restriction pointless."""
    for shell in ("bash", "sh", "cmd", "powershell", "pwsh", "zsh"):
        assert shell not in ALLOWED_EXECUTABLES
