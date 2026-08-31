"""Workflow execution context - the dependency-injection seam.

Nodes and agents receive this object.  They never construct a database session,
a Redis client, or an SDK client themselves (section 6, rule 5 of section 61),
which is what makes every node unit-testable with fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import Settings
from core.domain import EventType
from core.logging import get_logger
from infrastructure.events.base import Event, EventBus
from llm.base import LLMProvider, Usage
from persistence.db import session_scope
from persistence.repositories import (
    AgentRunRepository,
    ApprovalRepository,
    CIRunRepository,
    EventRepository,
    FileChangeRepository,
    TaskRepository,
    ToolCallRepository,
)
from policies.evaluator import PolicyEngine
from providers.ci.base import CIPipelineProvider
from providers.scm.base import SourceControlProvider
from tools.registry import ToolRegistry
from tools.workspace import WorkspaceManager

log = get_logger(__name__)


@dataclass
class WorkflowContext:
    settings: Settings
    llm: LLMProvider
    tools: ToolRegistry
    workspaces: WorkspaceManager
    policy: PolicyEngine
    scm: SourceControlProvider
    ci: CIPipelineProvider
    events: EventBus
    task_id: str
    workflow_run_id: str
    #: Set by the supervisor around each node so tool calls attribute correctly.
    current_agent_run_id: str | None = None
    usage: Usage = field(default_factory=Usage)
    prompts_path: Path = Path("prompts")

    # ---------------------------------------------------------------- events

    async def emit(self, event_type: EventType | str, **payload: Any) -> None:
        """Write the event to PostgreSQL (durable) and Redis (live)."""
        async with session_scope(self.settings) as session:
            record = await EventRepository(session).append(self.task_id, event_type, payload)
            sequence = record.sequence
        await self.events.publish(
            Event(
                task_id=self.task_id,
                type=str(event_type),
                payload=payload,
                sequence=sequence,
            )
        )

    # ----------------------------------------------------------------- audit

    async def record_tool_call(
        self,
        *,
        tool: str,
        arguments: dict[str, Any],
        ok: bool,
        result_preview: str | None,
        error: str | None,
        exit_code: int | None,
        duration_ms: int | None,
    ) -> None:
        async with session_scope(self.settings) as session:
            await ToolCallRepository(session).record(
                task_id=self.task_id,
                agent_run_id=self.current_agent_run_id,
                tool=tool,
                arguments=arguments,
                ok=ok,
                result_preview=result_preview,
                error=error,
                exit_code=exit_code,
                duration_ms=duration_ms,
            )

    async def record_file_change(
        self,
        *,
        path: str,
        change_type: str,
        iteration: int,
        lines_added: int = 0,
        lines_removed: int = 0,
    ) -> None:
        async with session_scope(self.settings) as session:
            await FileChangeRepository(session).record(
                task_id=self.task_id,
                path=path,
                change_type=change_type,
                iteration=iteration,
                lines_added=lines_added,
                lines_removed=lines_removed,
            )

    async def record_ci_run(self, **kwargs: Any) -> None:
        async with session_scope(self.settings) as session:
            await CIRunRepository(session).record(task_id=self.task_id, **kwargs)

    async def request_approval(self, reason: str) -> None:
        async with session_scope(self.settings) as session:
            repository = ApprovalRepository(session)
            if await repository.pending_for(self.task_id) is None:
                await repository.request(self.task_id, reason)

    async def start_agent_run(self, node: str, agent: str, iteration: int) -> str:
        async with session_scope(self.settings) as session:
            run = await AgentRunRepository(session).start(
                task_id=self.task_id,
                workflow_run_id=self.workflow_run_id,
                node=node,
                agent=agent,
                iteration=iteration,
            )
            return run.id

    async def finish_agent_run(
        self, agent_run_id: str, *, status: str, error: str | None = None, usage: Usage | None = None
    ) -> None:
        async with session_scope(self.settings) as session:
            await AgentRunRepository(session).finish(
                agent_run_id,
                status=status,
                error=error,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                cost_usd=usage.cost_usd if usage else 0.0,
            )

    async def save_checkpoint(self, state: dict[str, Any], *, node: str, status: Any) -> None:
        async with session_scope(self.settings) as session:
            repository = TaskRepository(session)
            await repository.save_state(self.task_id, dict(state))
            await repository.set_status(self.task_id, status, node=node)

    # ------------------------------------------------------------- prompts

    def load_prompt(self, name: str) -> str:
        path = self.prompts_path / f"{name}.md"
        if not path.exists():  # pragma: no cover - prompts ship with the repo
            raise FileNotFoundError(f"prompt not found: {path}")
        return path.read_text(encoding="utf-8")

    async def close(self) -> None:
        await self.llm.close()
        await self.scm.close()
        await self.ci.close()
