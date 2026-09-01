"""Worker consumer loop (sections 16, 38 and 39).

    while True:
        task = queue.receive()
        if task: execute(task)

Concurrency is a semaphore, so one worker process handles N tasks and the
deployment scales by adding worker replicas without a code change.
"""

from __future__ import annotations

import asyncio
import contextlib

from apps.worker.execution import TaskExecutor
from core.config import Settings
from core.logging import get_logger
from infrastructure import Coordination
from infrastructure.queue.base import QueuedTask
from infrastructure.queue.redis_queue import RedisTaskQueue
from persistence.db import session_scope
from persistence.repositories import TaskRepository

log = get_logger(__name__)


class WorkerConsumer:
    def __init__(
        self,
        settings: Settings,
        coordination: Coordination,
        worker_id: str,
        executor: TaskExecutor | None = None,
    ) -> None:
        self.settings = settings
        self.coordination = coordination
        self.worker_id = worker_id
        self.executor = executor or TaskExecutor(settings, coordination, worker_id)
        self.semaphore = asyncio.Semaphore(settings.worker_concurrency)
        self._running = False
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self) -> None:
        self._running = True
        log.info(
            "worker.started",
            worker=self.worker_id,
            concurrency=self.settings.worker_concurrency,
            backend=self.coordination.backend,
        )
        # Sweep once before waiting on the queue, so a worker that starts after
        # the API picks up anything already queued. A failure here must not stop
        # the worker from starting - the queue is the primary path.
        try:
            await self.sweep()
        except Exception:
            log.exception("worker.initial_sweep_failed")

        recovery = asyncio.create_task(self._recovery_loop())
        try:
            while self._running:
                item = await self.coordination.queue.receive(timeout_seconds=5.0)
                if item is None:
                    continue
                await self.semaphore.acquire()
                runner = asyncio.create_task(self._handle(item))
                self._tasks.add(runner)
                runner.add_done_callback(self._tasks.discard)
        finally:
            recovery.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recovery
            if self._tasks:
                await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._running = False

    async def run_once(self, timeout_seconds: float = 1.0) -> str | None:
        """Single-step form used by tests and by the demo script."""
        item = await self.coordination.queue.receive(timeout_seconds=timeout_seconds)
        if item is None:
            return None
        await self.semaphore.acquire()
        await self._handle(item)
        return item.task_id

    async def _handle(self, item: QueuedTask) -> None:
        try:
            await self.executor.execute(item.task_id)
            await self.coordination.queue.ack(item)
        # A failing task must not stop the loop: nack it and keep consuming.
        except Exception:
            log.exception("worker.task_failed", task_id=item.task_id)
            await self.coordination.queue.nack(item)
        finally:
            self.semaphore.release()

    async def _recovery_loop(self) -> None:
        """Reconcile the queue against the durable record (sections 39 and 55).

        Two jobs: pick up QUEUED tasks nobody is working on, and reclaim tasks
        whose worker died. Re-publishing an already-running task is harmless -
        the lock and the lease make the duplicate a no-op.
        """
        while self._running:
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("worker.recovery_failed")
            await asyncio.sleep(self.settings.queue_sweep_seconds)

    async def sweep(self) -> int:
        """One reconciliation pass. Returns how many tasks were re-published."""
        published = 0
        async with session_scope(self.settings) as session:
            repository = TaskRepository(session)
            unclaimed = await repository.find_unclaimed()
            stale = await repository.find_recoverable()

        for task in unclaimed:
            log.info("worker.sweep.queued", task_id=task.id)
            await self.coordination.queue.publish(task.id)
            published += 1

        for task in stale:
            log.warning("worker.reclaiming", task_id=task.id, previous=task.locked_by)
            await self.coordination.queue.publish(task.id)
            published += 1

        queue = self.coordination.queue
        if isinstance(queue, RedisTaskQueue):
            for item in await queue.reclaim_stale(
                min_idle_ms=self.settings.task_lease_seconds * 1000
            ):
                log.warning("worker.reclaimed_message", task_id=item.task_id)
                await self._handle(item)
        return published
