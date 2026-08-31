"""Tool gating (sections 9, 19, 25 and 53).

The three gates every tool call passes: the agent's allowlist, the policy
engine, and the workspace boundary.  Each is tested through the real agent loop
so the audit rows are produced too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.base import Agent
from core.errors import PolicyViolationError
from graph.context import WorkflowContext
from llm.scripted_provider import ScriptedTurn
from persistence.db import session_scope
from persistence.repositories import ToolCallRepository
from tools.base import ToolContext
from tools.registry import AGENT_TOOL_ALLOWLIST, ToolRegistry
from tools.workspace import Workspace


@pytest.fixture
def tool_context(sample_repository: Path) -> ToolContext:
    workspace = Workspace(
        task_id="TASK-test",
        path=sample_repository,
        branch="agent/TASK-test",
        repository_path=sample_repository,
    )
    return ToolContext(
        task_id="TASK-test",
        repository_path=sample_repository,
        workspace=workspace,
        iteration=0,
    )


class OneShotAgent(Agent):
    """A minimal agent bound to a chosen role, for exercising the gates."""

    def __init__(self, context: WorkflowContext, role: str) -> None:
        super().__init__(context)
        self.name = role


# ------------------------------------------------------------------ allowlist


def test_planner_has_no_tools() -> None:
    assert AGENT_TOOL_ALLOWLIST["planner"] == ()


def test_repository_agent_cannot_write() -> None:
    allowed = AGENT_TOOL_ALLOWLIST["repository"]
    assert "apply_patch" not in allowed
    assert "create_file" not in allowed
    assert "search_code" in allowed


def test_only_implementation_debugging_testing_and_ci_can_write() -> None:
    writers = {
        agent
        for agent, tools in AGENT_TOOL_ALLOWLIST.items()
        if "apply_patch" in tools or "create_file" in tools
    }
    assert writers == {"implementation", "testing", "debugging", "ci"}


def test_registry_rejects_an_unknown_agent() -> None:
    with pytest.raises(Exception):
        ToolRegistry().for_agent("nonexistent")


async def test_disallowed_tool_is_refused_and_audited(
    database, workflow_context: WorkflowContext, tool_context: ToolContext
) -> None:
    """A planner asking for apply_patch is refused by the platform, not the model."""
    workflow_context.llm.register(
        "planner",
        [
            ScriptedTurn.call("apply_patch", path="src/x.cs", old_text="a", new_text="b"),
            ScriptedTurn(text='{"summary":"done"}'),
        ],
    )
    agent = OneShotAgent(workflow_context, "planner")
    outcome = await agent.run(
        system="[agent:planner]", user_message="go", tool_context=tool_context
    )

    assert outcome.files_touched == []
    async with session_scope(database) as session:
        calls = await ToolCallRepository(session).list(workflow_context.task_id)
    assert len(calls) == 1
    assert calls[0].tool == "apply_patch"
    assert calls[0].ok is False
    assert "not available to the planner agent" in calls[0].error


# --------------------------------------------------------------------- policy


async def test_policy_blocks_a_write_to_a_secret_file(
    database, workflow_context: WorkflowContext, tool_context: ToolContext
) -> None:
    workflow_context.llm.register(
        "implementation",
        [ScriptedTurn.call("create_file", path=".env", content="SECRET=1")],
    )
    agent = OneShotAgent(workflow_context, "implementation")

    with pytest.raises(PolicyViolationError):
        await agent.run(
            system="[agent:implementation]", user_message="go", tool_context=tool_context
        )

    assert not (tool_context.workspace.path / ".env").exists(), "the file must never be written"


# ------------------------------------------------------------------ boundary


async def test_path_traversal_is_refused_and_reported_to_the_model(
    database, workflow_context: WorkflowContext, tool_context: ToolContext
) -> None:
    workflow_context.llm.register(
        "implementation",
        [
            ScriptedTurn.call("read_file", path="../../../../Windows/System32/drivers/etc/hosts"),
            ScriptedTurn(text='{"summary":"blocked"}'),
        ],
    )
    agent = OneShotAgent(workflow_context, "implementation")
    outcome = await agent.run(
        system="[agent:implementation]", user_message="go", tool_context=tool_context
    )

    assert outcome.turns == 2, "the agent should get the error back and continue"
    async with session_scope(database) as session:
        calls = await ToolCallRepository(session).list(workflow_context.task_id)
    assert calls[0].ok is False
    assert "escapes workspace" in calls[0].error


async def test_apply_patch_requires_a_unique_anchor(
    database, workflow_context: WorkflowContext, tool_context: ToolContext
) -> None:
    target = "src/OrderService/Services/OrderService.cs"
    workflow_context.llm.register(
        "implementation",
        [
            ScriptedTurn.call(
                "apply_patch", path=target, old_text="        return", new_text="        return  "
            ),
            ScriptedTurn(text='{"summary":"rejected"}'),
        ],
    )
    agent = OneShotAgent(workflow_context, "implementation")
    await agent.run(system="[agent:implementation]", user_message="go", tool_context=tool_context)

    async with session_scope(database) as session:
        calls = await ToolCallRepository(session).list(workflow_context.task_id)
    assert calls[0].ok is False
    assert "appears" in calls[0].error and "times" in calls[0].error


async def test_long_arguments_are_truncated_in_the_audit_row(
    database, workflow_context: WorkflowContext, tool_context: ToolContext
) -> None:
    workflow_context.llm.register(
        "implementation",
        [ScriptedTurn.call("create_file", path="src/Big.cs", content="x" * 5000)],
    )
    agent = OneShotAgent(workflow_context, "implementation")
    await agent.run(system="[agent:implementation]", user_message="go", tool_context=tool_context)

    async with session_scope(database) as session:
        calls = await ToolCallRepository(session).list(workflow_context.task_id)
    assert len(calls[0].arguments["content"]) < 600
    assert "more chars" in calls[0].arguments["content"]
