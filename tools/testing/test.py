"""Build / test / lint tools (sections 20 and 21).

Named operations only - ``run_dotnet_build``, ``run_dotnet_test`` - never an
arbitrary shell.  Test output is parsed into a structured result so the
debugging loop can fingerprint failures (section 23) instead of re-reading raw
logs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolContext, ToolResult
from tools.runner import CommandResult, run_command


@dataclass
class TestFailure:
    test_name: str
    exception_type: str = ""
    message: str = ""

    def render(self) -> str:
        head = f"{self.test_name}: {self.exception_type}".rstrip(": ")
        return f"{head}\n  {self.message}".rstrip()


@dataclass
class TestOutcome:
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    exit_code: int = 0
    output: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and not self.timed_out

    def summary(self) -> str:
        return (
            f"passed={self.passed} failed={self.failed} skipped={self.skipped} "
            f"exit_code={self.exit_code}"
        )


_DOTNET_TOTALS = re.compile(
    r"(?:Passed!|Failed!).*?Failed:\s*(\d+),\s*Passed:\s*(\d+),\s*Skipped:\s*(\d+)",
    re.IGNORECASE,
)
_VSTEST_TOTALS = re.compile(
    r"Total tests:\s*(\d+).*?Passed:\s*(\d+).*?Failed:\s*(\d+)", re.IGNORECASE | re.DOTALL
)
_FAILED_TEST = re.compile(r"^\s*(?:Failed|X)\s+([\w\.\+`]+(?:\([^)]*\))?)", re.MULTILINE)
_EXCEPTION = re.compile(r"([A-Za-z_][\w\.]*(?:Exception|Error))\s*:\s*(.*)")


def parse_dotnet_output(result: CommandResult) -> TestOutcome:
    text = result.combined_output
    outcome = TestOutcome(exit_code=result.exit_code, output=text, timed_out=result.timed_out)

    totals = _DOTNET_TOTALS.search(text)
    if totals:
        outcome.failed = int(totals.group(1))
        outcome.passed = int(totals.group(2))
        outcome.skipped = int(totals.group(3))
    else:
        vstest = _VSTEST_TOTALS.search(text)
        if vstest:
            outcome.passed = int(vstest.group(2))
            outcome.failed = int(vstest.group(3))

    seen: set[str] = set()
    for match in _FAILED_TEST.finditer(text):
        name = match.group(1).strip()
        if name in seen:
            continue
        seen.add(name)
        tail = text[match.end() : match.end() + 800]
        exception = _EXCEPTION.search(tail)
        outcome.failures.append(
            TestFailure(
                test_name=name,
                exception_type=exception.group(1) if exception else "",
                message=(exception.group(2).strip()[:400] if exception else tail.strip()[:400]),
            )
        )

    if outcome.failed == 0 and outcome.failures:
        outcome.failed = len(outcome.failures)
    if outcome.exit_code != 0 and outcome.failed == 0 and not outcome.passed:
        # Build error or crashed run - surface it as one synthetic failure.
        outcome.failed = 1
        outcome.failures.append(
            TestFailure(test_name="<test run>", exception_type="RunFailure", message=text[-600:])
        )
    return outcome


def detect_project_kind(root: Path) -> str:
    if any(root.rglob("*.sln")) or any(root.rglob("*.csproj")):
        return "dotnet"
    if (root / "package.json").exists():
        return "node"
    if (root / "pyproject.toml").exists():
        return "python"
    return "unknown"


async def run_dotnet_build(root: Path, timeout: int) -> CommandResult:
    return await run_command(
        ["dotnet", "build", "--nologo", "-v", "minimal"], cwd=root, timeout=timeout
    )


async def run_dotnet_test(root: Path, timeout: int, filter_expression: str | None = None) -> CommandResult:
    command = ["dotnet", "test", "--nologo", "-v", "minimal"]
    if filter_expression:
        command += ["--filter", filter_expression]
    return await run_command(command, cwd=root, timeout=timeout)


class BuildTool(Tool):
    name = "run_build"
    description = "Compile the project in the task workspace (dotnet build)."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def __init__(self, timeout: int = 600) -> None:
        self.timeout = timeout

    async def run(self, context: ToolContext, **_: Any) -> ToolResult:
        root = context.root
        kind = detect_project_kind(root)
        if kind != "dotnet":
            return ToolResult.failure(f"no dotnet project found in workspace (detected: {kind})")
        result = await run_dotnet_build(root, self.timeout)
        return ToolResult(
            ok=result.ok,
            content=result.combined_output[-8000:] or "build produced no output",
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Run the project's automated tests (dotnet test). Returns pass/fail counts and "
        "the failing test names with their exception messages."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "description": "Optional dotnet test --filter expression to narrow the run.",
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, timeout: int = 600) -> None:
        self.timeout = timeout

    async def run(self, context: ToolContext, *, filter: str | None = None, **_: Any) -> ToolResult:
        root = context.root
        kind = detect_project_kind(root)
        if kind != "dotnet":
            return ToolResult.failure(f"no dotnet project found in workspace (detected: {kind})")
        result = await run_dotnet_test(root, self.timeout, filter)
        outcome = parse_dotnet_output(result)
        body = outcome.summary()
        if outcome.failures:
            body += "\n\nFailures:\n" + "\n".join(f.render() for f in outcome.failures[:10])
        else:
            body += "\n\nAll tests passed."
        return ToolResult(
            ok=outcome.ok,
            content=body,
            data={
                "passed": outcome.passed,
                "failed": outcome.failed,
                "skipped": outcome.skipped,
                "failures": [f.render() for f in outcome.failures],
            },
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
