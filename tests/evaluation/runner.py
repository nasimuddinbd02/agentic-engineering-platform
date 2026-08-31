"""Evaluation harness (sections 42 and 48).

Runs benchmark fixtures against the platform and scores them from the durable
audit tables - the file_changes rows and the task record - rather than from the
model's own account of what it did.

    python -m tests.evaluation.runner --fixture issue-001
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))

FIXTURE_DIRECTORY = Path(__file__).parent


@dataclass
class EvaluationOutcome:
    fixture: str
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.fixture}"]
        for key, value in self.metrics.items():
            lines.append(f"    {key}: {value}")
        lines.extend(f"    ! {failure}" for failure in self.failures)
        return "\n".join(lines)


def load_fixtures(selector: str | None = None) -> list[dict[str, Any]]:
    fixtures = []
    for path in sorted(FIXTURE_DIRECTORY.glob("issue-*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if selector and selector not in (document.get("id"), document.get("name")):
            continue
        document["_path"] = str(path)
        fixtures.append(document)
    return fixtures


def score(fixture: dict[str, Any], observed: dict[str, Any]) -> EvaluationOutcome:
    """Compare a finished task against the fixture's expectations."""
    expect = fixture.get("expect", {})
    failures: list[str] = []

    discovered = set(observed.get("discovered_files", []))
    modified = set(observed.get("modified_files", []))

    expected_discovered = set(expect.get("discovered_files", []))
    if expected_discovered:
        found = expected_discovered & discovered
        recall = len(found) / len(expected_discovered)
        if recall < 1.0:
            failures.append(f"missed files: {sorted(expected_discovered - discovered)}")
    else:
        recall = 1.0

    for path in expect.get("modified_files", []):
        if path not in modified:
            failures.append(f"expected a change to {path}")

    any_of = expect.get("modified_files_any_of", [])
    if any_of and not (set(any_of) & modified):
        failures.append(f"expected a change to one of {any_of}")

    forbidden = set(expect.get("forbidden_files", [])) & modified
    if forbidden:
        failures.append(f"modified out-of-scope files: {sorted(forbidden)}")

    if "status" in expect and observed.get("status") != expect["status"]:
        failures.append(f"status was {observed.get('status')}, expected {expect['status']}")

    if "policy_action" in expect and observed.get("policy_action") != expect["policy_action"]:
        failures.append(
            f"policy action was {observed.get('policy_action')}, expected {expect['policy_action']}"
        )

    if "tests_failed" in expect and observed.get("tests_failed", 0) != expect["tests_failed"]:
        failures.append(f"tests_failed was {observed.get('tests_failed')}")

    if "min_tests_passed" in expect and observed.get("tests_passed", 0) < expect["min_tests_passed"]:
        failures.append(
            f"only {observed.get('tests_passed')} tests passed, "
            f"expected at least {expect['min_tests_passed']}"
        )

    if "max_iterations" in expect and observed.get("iterations", 0) > expect["max_iterations"]:
        failures.append(f"used {observed.get('iterations')} debugging iterations")

    if "risk_level_at_most" in expect:
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        if order.get(observed.get("risk_level", "LOW"), 0) > order[expect["risk_level_at_most"]]:
            failures.append(f"risk was {observed.get('risk_level')}")

    if expect.get("commit_created") is False and observed.get("commit_sha"):
        failures.append("a commit was created but the fixture forbids one")

    if "requires_approval" in expect and bool(observed.get("approval_required")) != bool(
        expect["requires_approval"]
    ):
        failures.append("approval_required did not match")

    metrics = {
        "retrieval_recall": round(recall, 3),
        "files_changed": len(modified),
        "out_of_scope_changes": len(forbidden),
        "iterations": observed.get("iterations", 0),
        "tests_passed": observed.get("tests_passed", 0),
        "tests_failed": observed.get("tests_failed", 0),
        "tool_calls": observed.get("tool_calls", 0),
        "duration_ms": observed.get("duration_ms", 0),
        "cost_usd": observed.get("cost_usd", 0.0),
    }
    return EvaluationOutcome(
        fixture=fixture.get("name", fixture.get("id", "unknown")),
        passed=not failures,
        metrics=metrics,
        failures=failures,
    )


async def observe(settings, task_id: str) -> dict[str, Any]:
    """Read what actually happened out of the audit tables."""
    from persistence.db import session_scope
    from persistence.repositories import (
        AgentRunRepository,
        EventRepository,
        FileChangeRepository,
        TaskRepository,
        ToolCallRepository,
    )

    async with session_scope(settings) as session:
        task = await TaskRepository(session).get(task_id)
        changes = await FileChangeRepository(session).list(task_id)
        calls = await ToolCallRepository(session).list(task_id)
        runs = await AgentRunRepository(session).list(task_id)
        events = await EventRepository(session).list(task_id)

    state = task.state or {}
    discovered: list[str] = []
    for event in events:
        if event.type == "FILES_DISCOVERED":
            discovered = list(event.payload.get("files", []))

    return {
        "status": task.status,
        "discovered_files": discovered,
        "modified_files": sorted({change.path for change in changes}),
        "policy_action": state.get("policy_action"),
        "tests_passed": state.get("tests_passed", 0),
        "tests_failed": state.get("tests_failed", 0),
        "iterations": task.iteration,
        "risk_level": task.risk_level or "LOW",
        "approval_required": task.approval_required,
        "commit_sha": task.commit_sha,
        "tool_calls": len(calls),
        "duration_ms": sum(run.duration_ms or 0 for run in runs),
        "cost_usd": round(sum(run.cost_usd for run in runs), 4),
    }


async def run_fixture(fixture: dict[str, Any], repository_path: Path) -> EvaluationOutcome:
    from apps.worker.execution import TaskExecutor
    from core.config import get_settings
    from infrastructure import build_coordination
    from persistence.db import create_schema, session_scope
    from persistence.repositories import EvaluationRepository, TaskRepository

    settings = get_settings()
    await create_schema(settings)

    async with session_scope(settings) as session:
        task = await TaskRepository(session).create(
            repository_url=repository_path.as_uri(),
            repository_path=str(repository_path),
            issue=fixture["issue"],
            created_by="evaluation",
        )
        task_id = task.id

    coordination = build_coordination(settings, consumer_name="evaluation")
    executor = TaskExecutor(settings, coordination, worker_id="evaluation")
    await executor.execute(task_id)

    observed = await observe(settings, task_id)
    outcome = score(fixture, observed)

    async with session_scope(settings) as session:
        await EvaluationRepository(session).record(
            fixture=outcome.fixture,
            task_id=task_id,
            passed=outcome.passed,
            metrics=outcome.metrics,
            details={"failures": outcome.failures, "observed": observed},
        )
    return outcome


async def main_async(selector: str | None, repository_path: Path) -> int:
    fixtures = load_fixtures(selector)
    if not fixtures:
        print(f"no fixtures matched {selector!r}", file=sys.stderr)
        return 1

    outcomes = [await run_fixture(fixture, repository_path) for fixture in fixtures]
    print("\n".join(outcome.render() for outcome in outcomes))

    passed = sum(1 for outcome in outcomes if outcome.passed)
    print(f"\n{passed}/{len(outcomes)} fixtures passed")

    from persistence.db import dispose_engine

    await dispose_engine()
    return 0 if passed == len(outcomes) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agent evaluation benchmark.")
    parser.add_argument("--fixture", default=None, help="fixture id or name; default is all")
    parser.add_argument(
        "--repository-path",
        type=Path,
        default=REPOSITORY_ROOT / ".sandbox" / "order-service",
    )
    arguments = parser.parse_args()

    repository_path = arguments.repository_path.expanduser().resolve()
    if not repository_path.is_dir():
        print(
            f"repository not found: {repository_path}\nrun `python -m scripts.bootstrap` first",
            file=sys.stderr,
        )
        return 1

    return asyncio.run(main_async(arguments.fixture, repository_path))


if __name__ == "__main__":
    raise SystemExit(main())
