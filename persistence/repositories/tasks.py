"""Task repository - the only module that knows how a task is stored.

Agents never see this class; they go through the application services
(section 6).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain import TERMINAL_STATUSES, TaskStatus
from core.ids import task_id as new_task_id
from core.time import utcnow
from persistence.models import IdempotencyRecord, Task


def fingerprint(repository_url: str, issue: str) -> str:
    return hashlib.sha256(f"{repository_url}\n{issue}".encode()).hexdigest()[:64]


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ reads

    async def get(self, task_id: str) -> Task | None:
        return await self.session.get(Task, task_id)

    async def list(self, limit: int = 50, status: str | None = None) -> list[Task]:
        stmt = select(Task).order_by(Task.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Task.status == status)
        return list((await self.session.scalars(stmt)).all())

    async def find_by_idempotency_key(self, key: str) -> IdempotencyRecord | None:
        return await self.session.get(IdempotencyRecord, key)

    # ----------------------------------------------------------------- writes

    async def create(
        self,
        *,
        repository_url: str,
        repository_path: str | None,
        issue: str,
        created_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        task = Task(
            id=new_task_id(),
            repository_url=repository_url,
            repository_path=repository_path,
            issue=issue,
            status=TaskStatus.QUEUED,
            created_by=created_by,
            idempotency_key=idempotency_key,
            state={},
        )
        self.session.add(task)
        if idempotency_key:
            self.session.add(
                IdempotencyRecord(
                    key=idempotency_key,
                    task_id=task.id,
                    request_fingerprint=fingerprint(repository_url, issue),
                )
            )
        await self.session.flush()
        return task

    async def set_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        node: str | None = None,
        error: str | None = None,
    ) -> None:
        values: dict = {"status": status.value, "updated_at": utcnow()}
        if node is not None:
            values["current_node"] = node
        if error is not None:
            values["error"] = error
        if status in TERMINAL_STATUSES:
            values["finished_at"] = utcnow()
            values["locked_by"] = None
            values["lease_expires_at"] = None
        await self.session.execute(update(Task).where(Task.id == task_id).values(**values))

    async def save_state(self, task_id: str, state: dict) -> None:
        """Persist the workflow checkpoint so any worker can resume (section 55)."""
        task = await self.session.get(Task, task_id)
        if task is None:
            return
        task.state = state
        task.iteration = int(state.get("iteration", task.iteration))
        task.ci_iteration = int(state.get("ci_iteration", task.ci_iteration))
        task.risk_level = state.get("risk_level") or task.risk_level
        task.workspace_path = state.get("workspace_path") or task.workspace_path
        task.branch = state.get("git_branch") or task.branch
        task.commit_sha = state.get("commit_sha") or task.commit_sha
        task.pull_request_url = state.get("pull_request_url") or task.pull_request_url
        task.approval_required = bool(state.get("approval_required", task.approval_required))
        task.summary = state.get("final_summary") or task.summary
        task.updated_at = utcnow()

    # ------------------------------------------------------------- leasing

    async def claim(self, task_id: str, worker_id: str, lease_seconds: int) -> Task | None:
        """Take the durable half of the lock (section 17).

        Redis holds the fast lock; this conditional UPDATE is the second safety
        mechanism, so a stale Redis lock can never produce two live executions.
        """
        now = utcnow()
        expires = now + timedelta(seconds=lease_seconds)
        stmt = (
            update(Task)
            .where(
                Task.id == task_id,
                Task.status.not_in([s.value for s in TERMINAL_STATUSES]),
                (Task.locked_by.is_(None)) | (Task.lease_expires_at < now),
            )
            .values(
                locked_by=worker_id,
                lease_expires_at=expires,
                started_at=Task.started_at,
                updated_at=now,
            )
        )
        # synchronize_session=False: the WHERE clause is evaluated by the
        # database, not re-evaluated in Python against identity-mapped objects.
        result = await self.session.execute(
            stmt.execution_options(synchronize_session=False)
        )
        if result.rowcount == 0:
            return None
        task = await self.session.get(Task, task_id, populate_existing=True)
        if task is not None and task.started_at is None:
            task.started_at = now
        return task

    async def renew_lease(self, task_id: str, worker_id: str, lease_seconds: int) -> bool:
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.locked_by == worker_id)
            .values(lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount > 0

    async def release(self, task_id: str, worker_id: str) -> None:
        await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.locked_by == worker_id)
            .values(locked_by=None, lease_expires_at=None)
            .execution_options(synchronize_session=False)
        )

    async def find_unclaimed(self, limit: int = 20) -> list[Task]:
        """QUEUED tasks that no worker holds.

        A reconciliation sweep against the durable record. It closes the gap
        between "the task row is committed" and "the queue message was
        published" - and it is what lets a worker process pick up work when the
        queue adapter is in-process (REDIS_URL=memory://).
        """
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.QUEUED.value, Task.locked_by.is_(None))
            .order_by(Task.created_at)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def find_recoverable(self, limit: int = 20) -> list[Task]:
        """Tasks whose worker died: lease expired but the task is not finished."""
        now = utcnow()
        stmt = (
            select(Task)
            .where(
                Task.status.not_in([s.value for s in TERMINAL_STATUSES]),
                Task.status != TaskStatus.READY_FOR_REVIEW.value,
                Task.locked_by.is_not(None),
                Task.lease_expires_at < now,
            )
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())
