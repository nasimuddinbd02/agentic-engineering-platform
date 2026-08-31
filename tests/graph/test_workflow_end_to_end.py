"""End-to-end workflow tests (section 47, "End-to-end tests").

Issue -> agent -> code change -> tests -> debug -> git, against the real sample
repository, the real Git worktree and a real ``dotnet test`` run.  Only the
model is scripted.
"""

from __future__ import annotations

import pytest

from apps.worker.execution import TaskExecutor
from core.domain import TaskStatus
from persistence.db import session_scope
from persistence.repositories import (
    AgentRunRepository,
    ApprovalRepository,
    EventRepository,
    FileChangeRepository,
    TaskRepository,
    ToolCallRepository,
)
from tests.conftest import requires_dotnet
from tests.graph.scripts import (
    TARGET_FILE,
    TEST_FILE,
    debugging_path_script,
    happy_path_script,
    stuck_script,
)

pytestmark = [pytest.mark.slow, requires_dotnet]


async def run_task(settings, coordination, scripted_llm, script, task_id) -> dict:
    scripted_llm.script.update(script)
    executor = TaskExecutor(settings, coordination, worker_id="worker-test")

    # Inject the scripted provider in place of the configured one.
    import apps.worker.execution as execution_module

    original = execution_module.build_llm_provider
    execution_module.build_llm_provider = lambda _settings=None: scripted_llm
    try:
        return await executor.execute(task_id)
    finally:
        execution_module.build_llm_provider = original


async def test_happy_path_reaches_review(
    database, coordination, scripted_llm, seeded_task, settings
):
    result = await run_task(
        settings, coordination, scripted_llm, happy_path_script(), seeded_task
    )

    assert result["status"] == TaskStatus.READY_FOR_REVIEW.value
    assert result["tests"]["failed"] == 0
    # 7 original tests plus the 2 the agent added.
    assert result["tests"]["passed"] == 9
    assert result["iterations"] == 0
    assert TARGET_FILE in result["files_changed"]
    assert TEST_FILE in result["files_changed"]
    assert result["branch"] == f"agent/{seeded_task}"
    assert result["pull_request_url"]
    assert result["approval_required"] is True

    async with session_scope(database) as session:
        task = await TaskRepository(session).get(seeded_task)
        assert task.status == TaskStatus.READY_FOR_REVIEW.value
        assert task.commit_sha
        assert task.risk_level == "LOW"

        # The audit trail of section 58 must answer "what did the agent do".
        events = await EventRepository(session).list(seeded_task)
        types = [event.type for event in events]
        for expected in (
            "PLAN_CREATED",
            "FILES_DISCOVERED",
            "RISK_ASSESSED",
            "WORKSPACE_CREATED",
            "FILE_CHANGED",
            "TESTS_PASSED",
            "POLICY_EVALUATED",
            "COMMIT_CREATED",
            "PR_CREATED",
            "APPROVAL_REQUESTED",
        ):
            assert expected in types, f"missing event {expected}"
        assert [event.sequence for event in events] == sorted(e.sequence for e in events)

        tool_calls = await ToolCallRepository(session).list(seeded_task)
        assert {call.tool for call in tool_calls} >= {
            "search_code",
            "read_file",
            "apply_patch",
            "create_file",
        }
        changes = await FileChangeRepository(session).list(seeded_task)
        assert {change.path for change in changes} == {TARGET_FILE, TEST_FILE}

        runs = await AgentRunRepository(session).list(seeded_task)
        assert {run.node for run in runs} >= {
            "plan",
            "repository_analysis",
            "risk_assessment",
            "implementation",
            "test_generation",
            "run_tests",
            "security_policy",
            "git_commit",
            "create_pr",
            "human_review",
        }
        assert all(run.status == "COMPLETED" for run in runs)

        approval = await ApprovalRepository(session).pending_for(seeded_task)
        assert approval is not None and approval.status == "PENDING"


async def test_failing_tests_trigger_bounded_debugging(
    database, coordination, scripted_llm, seeded_task, settings
):
    result = await run_task(
        settings, coordination, scripted_llm, debugging_path_script(), seeded_task
    )

    assert result["status"] == TaskStatus.READY_FOR_REVIEW.value
    assert result["iterations"] == 1, "the debugger should have needed exactly one pass"
    assert result["tests"]["failed"] == 0
    assert result["tests"]["passed"] == 9

    async with session_scope(database) as session:
        types = [event.type for event in await EventRepository(session).list(seeded_task)]
        assert "TEST_FAILED" in types
        assert "DEBUG_ITERATION" in types
        assert types.index("TEST_FAILED") < types.index("DEBUG_ITERATION")
        assert "TESTS_PASSED" in types
        assert types.index("DEBUG_ITERATION") < types.index("TESTS_PASSED")

        task = await TaskRepository(session).get(seeded_task)
        assert task.iteration == 1
        assert task.state["debugging_analysis"]


async def test_stuck_debugging_stops_and_escalates(
    database, coordination, scripted_llm, seeded_task, settings
):
    """The loop must halt on repeated identical failures, not spin (section 23)."""
    result = await run_task(settings, coordination, scripted_llm, stuck_script(), seeded_task)

    assert result["status"] == TaskStatus.HUMAN_REVIEW_REQUIRED.value
    assert result["iterations"] <= settings.max_agent_iterations
    assert not result["pull_request_url"]

    async with session_scope(database) as session:
        task = await TaskRepository(session).get(seeded_task)
        assert task.status == TaskStatus.HUMAN_REVIEW_REQUIRED.value
        assert task.commit_sha is None, "a failing change must never be committed"
        types = [event.type for event in await EventRepository(session).list(seeded_task)]
        assert "NO_PROGRESS_DETECTED" in types
        assert "COMMIT_CREATED" not in types
