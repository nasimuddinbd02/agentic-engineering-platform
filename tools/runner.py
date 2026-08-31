"""Command execution (section 20).

There is no ``run_any_shell_command``.  Callers pass an argument vector whose
first element must be on the allowlist, the process is spawned without a shell,
and every execution is recorded: command, timing, exit code, stdout, stderr.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

from core.errors import WorkspaceViolationError
from core.logging import get_logger

log = get_logger(__name__)

#: Executables the platform may spawn.  Everything else is refused.
ALLOWED_EXECUTABLES: frozenset[str] = frozenset(
    {"git", "dotnet", "npm", "node", "python", "ruff", "pytest"}
)

MAX_OUTPUT_CHARS = 200_000


@dataclass
class CommandResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return f"{text[:half]}\n...[{len(text) - MAX_OUTPUT_CHARS} chars truncated]...\n{text[-half:]}"


async def run_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> CommandResult:
    if not command:
        raise WorkspaceViolationError("empty command")
    executable = Path(command[0]).stem.lower()
    if executable not in ALLOWED_EXECUTABLES:
        raise WorkspaceViolationError(f"executable not allowed: {command[0]}")

    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise WorkspaceViolationError(f"working directory does not exist: {cwd}")

    process_env = {**os.environ, **(env or {})}
    # Keep agent-run builds from touching shared developer state.
    process_env.setdefault("DOTNET_CLI_TELEMETRY_OPTOUT", "1")
    process_env.setdefault("DOTNET_NOLOGO", "1")
    process_env.setdefault("GIT_TERMINAL_PROMPT", "0")

    started = time.perf_counter()
    timed_out = False
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
        )
    except FileNotFoundError as exc:
        raise WorkspaceViolationError(f"executable not found: {command[0]}") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except (TimeoutError, asyncio.TimeoutError):
        timed_out = True
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()

    duration_ms = int((time.perf_counter() - started) * 1000)
    result = CommandResult(
        command=command,
        cwd=str(cwd),
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=_truncate(stdout_bytes.decode("utf-8", errors="replace")),
        stderr=_truncate(stderr_bytes.decode("utf-8", errors="replace")),
        duration_ms=duration_ms,
        timed_out=timed_out,
    )
    log.info(
        "command.executed",
        command=" ".join(command),
        cwd=str(cwd),
        exit_code=result.exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
    )
    return result
