"""Audit repositories: events, agent runs, tool calls, file changes, CI, approvals.

Section 58 lists the questions this data must answer.  Every write here is
append-only.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain import EventType
from core.ids import event_id, new_id, run_id, tool_call_id
from core.time import as_aware, utcnow
from persistence.models import (
    AgentRun,
    Approval,
    CIRun,
    EvaluationResult,
    FileChange,
    TaskEvent,
    ToolCall,
)


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(
        self, task_id: str, event_type: EventType | str, payload: dict | None = None
    ) -> TaskEvent:
        next_sequence = (
            await self.session.scalar(
                select(func.coalesce(func.max(TaskEvent.sequence), 0) + 1).where(
                    TaskEvent.task_id == task_id
                )
            )
        ) or 1
        event = TaskEvent(
            id=event_id(),
            task_id=task_id,
            sequence=next_sequence,
            type=str(event_type),
            payload=payload or {},
            created_at=utcnow(),
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list(self, task_id: str, after_sequence: int = 0) -> list[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.sequence > after_sequence)
            .order_by(TaskEvent.sequence)
        )
        return list((await self.session.scalars(stmt)).all())


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(
        self, *, task_id: str, workflow_run_id: str, node: str, agent: str, iteration: int
    ) -> AgentRun:
        run = AgentRun(
            id=run_id(),
            task_id=task_id,
            workflow_run_id=workflow_run_id,
            node=node,
            agent=agent,
            iteration=iteration,
            status="RUNNING",
            started_at=utcnow(),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish(
        self,
        run_identifier: str,
        *,
        status: str,
        error: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        run = await self.session.get(AgentRun, run_identifier)
        if run is None:
            return
        run.status = status
        run.error = error
        run.finished_at = utcnow()
        run.input_tokens += input_tokens
        run.output_tokens += output_tokens
        run.cost_usd += cost_usd
        started = as_aware(run.started_at)
        finished = as_aware(run.finished_at)
        if started and finished:
            run.duration_ms = int((finished - started).total_seconds() * 1000)

    async def list(self, task_id: str) -> list[AgentRun]:
        stmt = select(AgentRun).where(AgentRun.task_id == task_id).order_by(AgentRun.created_at)
        return list((await self.session.scalars(stmt)).all())


class ToolCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        task_id: str,
        agent_run_id: str | None,
        tool: str,
        arguments: dict,
        ok: bool,
        result_preview: str | None = None,
        error: str | None = None,
        exit_code: int | None = None,
        duration_ms: int | None = None,
    ) -> ToolCall:
        call = ToolCall(
            id=tool_call_id(),
            task_id=task_id,
            agent_run_id=agent_run_id,
            tool=tool,
            arguments=arguments,
            ok=ok,
            result_preview=(result_preview or "")[:4000] or None,
            error=error,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        self.session.add(call)
        await self.session.flush()
        return call

    async def list(self, task_id: str) -> list[ToolCall]:
        stmt = select(ToolCall).where(ToolCall.task_id == task_id).order_by(ToolCall.created_at)
        return list((await self.session.scalars(stmt)).all())


class FileChangeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        task_id: str,
        path: str,
        change_type: str,
        iteration: int,
        lines_added: int = 0,
        lines_removed: int = 0,
        diff: str | None = None,
    ) -> FileChange:
        change = FileChange(
            id=new_id("fc"),
            task_id=task_id,
            path=path,
            change_type=change_type,
            iteration=iteration,
            lines_added=lines_added,
            lines_removed=lines_removed,
            diff=diff,
        )
        self.session.add(change)
        await self.session.flush()
        return change

    async def list(self, task_id: str) -> list[FileChange]:
        stmt = (
            select(FileChange).where(FileChange.task_id == task_id).order_by(FileChange.created_at)
        )
        return list((await self.session.scalars(stmt)).all())


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def request(self, task_id: str, reason: str) -> Approval:
        approval = Approval(
            id=new_id("apr"), task_id=task_id, status="PENDING", requested_reason=reason
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def pending_for(self, task_id: str) -> Approval | None:
        stmt = (
            select(Approval)
            .where(Approval.task_id == task_id, Approval.status == "PENDING")
            .order_by(Approval.created_at.desc())
        )
        return (await self.session.scalars(stmt)).first()

    async def decide(
        self, approval_id: str, *, status: str, decided_by: str | None, reason: str | None
    ) -> Approval | None:
        approval = await self.session.get(Approval, approval_id)
        if approval is None:
            return None
        approval.status = status
        approval.decided_by = decided_by
        approval.reason = reason
        approval.decided_at = utcnow()
        return approval

    async def list(self, task_id: str) -> list[Approval]:
        stmt = select(Approval).where(Approval.task_id == task_id).order_by(Approval.created_at)
        return list((await self.session.scalars(stmt)).all())


class CIRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        task_id: str,
        provider: str,
        external_id: str | None,
        branch: str | None,
        status: str,
        conclusion: str | None = None,
        url: str | None = None,
        logs: str | None = None,
        iteration: int = 0,
    ) -> CIRun:
        run = CIRun(
            id=new_id("ci"),
            task_id=task_id,
            provider=provider,
            external_id=external_id,
            branch=branch,
            status=status,
            conclusion=conclusion,
            url=url,
            logs=(logs or "")[:20000] or None,
            iteration=iteration,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def list(self, task_id: str) -> list[CIRun]:
        stmt = select(CIRun).where(CIRun.task_id == task_id).order_by(CIRun.created_at)
        return list((await self.session.scalars(stmt)).all())


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        fixture: str,
        task_id: str | None,
        passed: bool,
        metrics: dict,
        details: dict,
    ) -> EvaluationResult:
        result = EvaluationResult(
            id=new_id("eval"),
            fixture=fixture,
            task_id=task_id,
            passed=passed,
            metrics=metrics,
            details=details,
        )
        self.session.add(result)
        await self.session.flush()
        return result
