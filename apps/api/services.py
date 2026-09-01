"""Application services.

FastAPI routes call these; these call repositories and the queue.  Agents are
never reachable from a request handler - a POST returns 202 and the work happens
in a worker (sections 2.2 and 15).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.domain import TERMINAL_STATUSES, EventType, TaskStatus
from core.errors import InvalidTaskTransitionError, TaskNotFoundError
from core.logging import get_logger
from infrastructure.events.base import Event, EventBus
from infrastructure.queue.base import TaskQueue
from persistence.models import Task
from persistence.repositories import (
    AgentRunRepository,
    ApprovalRepository,
    CIRunRepository,
    EventRepository,
    FileChangeRepository,
    TaskRepository,
    ToolCallRepository,
    fingerprint,
)

log = get_logger(__name__)


class TaskService:
    def __init__(self, session: AsyncSession, queue: TaskQueue, events: EventBus) -> None:
        self.session = session
        self.queue = queue
        self.events = events
        self.tasks = TaskRepository(session)
        self.event_log = EventRepository(session)

    async def _publish(self, task_id: str, event_type: EventType, **payload: Any) -> None:
        record = await self.event_log.append(task_id, event_type, payload)
        await self.events.publish(
            Event(
                task_id=task_id,
                type=str(event_type),
                payload=payload,
                sequence=record.sequence,
            )
        )

    # ------------------------------------------------------------- creation

    async def create_task(
        self,
        *,
        repository_url: str,
        repository_path: str | None,
        issue: str,
        created_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[Task, bool]:
        """Returns (task, created). Replays the same key to the same task (section 52)."""
        if idempotency_key:
            existing = await self.tasks.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint(repository_url, issue):
                    raise InvalidTaskTransitionError(
                        "Idempotency-Key was already used for a different request"
                    )
                task = await self.tasks.get(existing.task_id)
                if task is not None:
                    return task, False

        task = await self.tasks.create(
            repository_url=repository_url,
            repository_path=repository_path,
            issue=issue,
            created_by=created_by,
            idempotency_key=idempotency_key,
        )
        await self._publish(task.id, EventType.TASK_CREATED, repository=repository_url)
        # Committed by the request-scoped session before the worker can pick it up.
        return task, True

    async def enqueue(self, task_id: str) -> None:
        await self.queue.publish(task_id)
        log.info("task.enqueued", task_id=task_id)

    # ---------------------------------------------------------------- reads

    async def get(self, task_id: str) -> Task:
        task = await self.tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def list(self, limit: int = 50, status: str | None = None) -> list[Task]:
        return await self.tasks.list(limit=limit, status=status)

    async def detail(self, task_id: str) -> dict[str, Any]:
        task = await self.get(task_id)
        return {
            "task": task,
            "events": await self.event_log.list(task_id),
            "runs": await AgentRunRepository(self.session).list(task_id),
            "tool_calls": await ToolCallRepository(self.session).list(task_id),
            "file_changes": await FileChangeRepository(self.session).list(task_id),
            "ci_runs": await CIRunRepository(self.session).list(task_id),
            "approvals": await ApprovalRepository(self.session).list(task_id),
        }

    async def events_since(self, task_id: str, after_sequence: int = 0) -> list[Any]:
        await self.get(task_id)
        return await self.event_log.list(task_id, after_sequence=after_sequence)

    async def diff(self, task_id: str) -> str:
        task = await self.get(task_id)
        return str(task.state.get("git_diff", "")) if task.state else ""

    # ------------------------------------------------------------ decisions

    async def approve(self, task_id: str, *, decided_by: str | None, reason: str | None) -> Task:
        task = await self.get(task_id)
        if task.status != TaskStatus.READY_FOR_REVIEW.value:
            raise InvalidTaskTransitionError(
                f"task {task_id} is {task.status}, not READY_FOR_REVIEW"
            )
        approvals = ApprovalRepository(self.session)
        pending = await approvals.pending_for(task_id)
        if pending is not None:
            await approvals.decide(
                pending.id, status="APPROVED", decided_by=decided_by, reason=reason
            )
        await self.tasks.set_status(task_id, TaskStatus.HUMAN_APPROVED)
        await self._publish(task_id, EventType.APPROVAL_GRANTED, decided_by=decided_by)
        # The protected operation - merging - stays with the human (section 54).
        await self.tasks.set_status(task_id, TaskStatus.COMPLETED)
        await self._publish(task_id, EventType.TASK_COMPLETED, decided_by=decided_by)
        return await self.get(task_id)

    async def reject(self, task_id: str, *, decided_by: str | None, reason: str | None) -> Task:
        task = await self.get(task_id)
        if (
            task.status in TERMINAL_STATUSES
            and task.status != TaskStatus.HUMAN_REVIEW_REQUIRED.value
        ):
            raise InvalidTaskTransitionError(f"task {task_id} is already {task.status}")
        approvals = ApprovalRepository(self.session)
        pending = await approvals.pending_for(task_id)
        if pending is not None:
            await approvals.decide(
                pending.id, status="REJECTED", decided_by=decided_by, reason=reason
            )
        await self.tasks.set_status(task_id, TaskStatus.REJECTED, error=reason)
        await self._publish(
            task_id, EventType.APPROVAL_REJECTED, decided_by=decided_by, reason=reason
        )
        return await self.get(task_id)

    async def cancel(self, task_id: str, *, reason: str | None = None) -> Task:
        task = await self.get(task_id)
        if task.status in TERMINAL_STATUSES:
            raise InvalidTaskTransitionError(f"task {task_id} is already {task.status}")
        await self.tasks.set_status(task_id, TaskStatus.CANCELLED, error=reason)
        await self._publish(task_id, EventType.TASK_CANCELLED, reason=reason)
        return await self.get(task_id)
