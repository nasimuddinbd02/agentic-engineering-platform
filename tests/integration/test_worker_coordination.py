"""Worker coordination (sections 16, 17, 38, 39 and 55).

The properties that make horizontal scaling safe: one task is executed once,
a dead worker's lease expires and the task becomes recoverable, and the queue
survives a nack.
"""

from __future__ import annotations

import asyncio

import pytest

from apps.worker.consumer import WorkerConsumer
from core.config import Settings
from core.domain import TaskStatus
from infrastructure.locks.memory_lock import MemoryLockManager
from infrastructure.queue.memory_queue import MemoryTaskQueue
from persistence.db import session_scope
from persistence.repositories import TaskRepository


# ------------------------------------------------------------------- queue


async def test_queue_round_trip() -> None:
    queue = MemoryTaskQueue()
    assert await queue.receive(timeout_seconds=0.05) is None

    await queue.publish("TASK-1")
    assert await queue.depth() == 1

    item = await queue.receive(timeout_seconds=1.0)
    assert item is not None and item.task_id == "TASK-1"
    await queue.ack(item)
    assert await queue.depth() == 0


async def test_nack_returns_the_task_to_the_queue() -> None:
    queue = MemoryTaskQueue()
    await queue.publish("TASK-1")
    item = await queue.receive(timeout_seconds=1.0)
    await queue.nack(item)
    again = await queue.receive(timeout_seconds=1.0)
    assert again.task_id == "TASK-1"


# -------------------------------------------------------------------- locks


async def test_lock_is_exclusive() -> None:
    locks = MemoryLockManager()
    assert await locks.acquire("task:1", 60, "worker-a")
    assert not await locks.acquire("task:1", 60, "worker-b")

    await locks.release("task:1", "worker-b")
    assert not await locks.acquire("task:1", 60, "worker-b"), "a non-owner cannot release"

    await locks.release("task:1", "worker-a")
    assert await locks.acquire("task:1", 60, "worker-b")


async def test_lock_expires() -> None:
    locks = MemoryLockManager()
    assert await locks.acquire("task:1", 0, "worker-a")
    await asyncio.sleep(0.01)
    assert await locks.acquire("task:1", 60, "worker-b"), "an expired lock must be reclaimable"


async def test_only_the_owner_can_renew() -> None:
    locks = MemoryLockManager()
    await locks.acquire("task:1", 60, "worker-a")
    assert await locks.renew("task:1", 60, "worker-a")
    assert not await locks.renew("task:1", 60, "worker-b")


# ------------------------------------------------------------------- leases


async def test_claim_is_exclusive_across_workers(database: Settings, seeded_task: str) -> None:
    async with session_scope(database) as session:
        repository = TaskRepository(session)
        assert await repository.claim(seeded_task, "worker-a", 900) is not None

    async with session_scope(database) as session:
        assert await TaskRepository(session).claim(seeded_task, "worker-b", 900) is None


async def test_expired_lease_can_be_reclaimed(database: Settings, seeded_task: str) -> None:
    async with session_scope(database) as session:
        await TaskRepository(session).claim(seeded_task, "worker-a", lease_seconds=-1)

    async with session_scope(database) as session:
        repository = TaskRepository(session)
        recoverable = await repository.find_recoverable()
        assert seeded_task in [task.id for task in recoverable]
        assert await repository.claim(seeded_task, "worker-b", 900) is not None


async def test_finished_task_is_not_recoverable(database: Settings, seeded_task: str) -> None:
    async with session_scope(database) as session:
        repository = TaskRepository(session)
        await repository.claim(seeded_task, "worker-a", lease_seconds=-1)
        await repository.set_status(seeded_task, TaskStatus.COMPLETED)

    async with session_scope(database) as session:
        recoverable = await TaskRepository(session).find_recoverable()
        assert seeded_task not in [task.id for task in recoverable]


async def test_terminal_task_cannot_be_claimed(database: Settings, seeded_task: str) -> None:
    async with session_scope(database) as session:
        await TaskRepository(session).set_status(seeded_task, TaskStatus.CANCELLED)
    async with session_scope(database) as session:
        assert await TaskRepository(session).claim(seeded_task, "worker-a", 900) is None


# ------------------------------------------------------------------ consumer


class RecordingExecutor:
    """Stands in for the real executor so the loop can be tested in isolation."""

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.concurrent = 0
        self.peak = 0

    async def execute(self, task_id: str) -> dict:
        self.concurrent += 1
        self.peak = max(self.peak, self.concurrent)
        await asyncio.sleep(0.02)
        self.executed.append(task_id)
        self.concurrent -= 1
        return {"task_id": task_id}


async def test_consumer_executes_queued_tasks(
    database: Settings, settings: Settings, coordination
) -> None:
    executor = RecordingExecutor()
    consumer = WorkerConsumer(settings, coordination, "worker-test", executor)  # type: ignore[arg-type]

    await coordination.queue.publish("TASK-1")
    assert await consumer.run_once(timeout_seconds=1.0) == "TASK-1"
    assert executor.executed == ["TASK-1"]


async def test_consumer_respects_the_concurrency_limit(
    database: Settings, settings: Settings, coordination
) -> None:
    settings = settings.model_copy(update={"worker_concurrency": 2})
    executor = RecordingExecutor()
    consumer = WorkerConsumer(settings, coordination, "worker-test", executor)  # type: ignore[arg-type]

    for index in range(6):
        await coordination.queue.publish(f"TASK-{index}")

    runner = asyncio.create_task(consumer.run_forever())
    await asyncio.sleep(0.4)
    await consumer.stop()
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner

    assert len(executor.executed) == 6
    assert executor.peak <= 2, "the semaphore must cap in-flight tasks"


async def test_failing_task_is_nacked_not_lost(
    database: Settings, settings: Settings, coordination
) -> None:
    class FailingExecutor:
        async def execute(self, task_id: str) -> dict:
            raise RuntimeError("boom")

    consumer = WorkerConsumer(settings, coordination, "worker-test", FailingExecutor())  # type: ignore[arg-type]
    await coordination.queue.publish("TASK-X")
    await consumer.run_once(timeout_seconds=1.0)

    requeued = await coordination.queue.receive(timeout_seconds=1.0)
    assert requeued is not None and requeued.task_id == "TASK-X"
