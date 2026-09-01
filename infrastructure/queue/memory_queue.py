"""In-process queue for single-process development and tests.

It implements the same contract as the Redis adapter, but it is explicitly not
multi-process: choosing ``REDIS_URL=memory://`` gives up horizontal scaling.
"""

from __future__ import annotations

import asyncio

from infrastructure.queue.base import QueuedTask, TaskQueue


class MemoryTaskQueue(TaskQueue):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._in_flight: set[str] = set()

    async def publish(self, task_id: str) -> None:
        await self._queue.put(task_id)

    async def receive(self, timeout_seconds: float = 5.0) -> QueuedTask | None:
        try:
            task_id = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None
        self._in_flight.add(task_id)
        return QueuedTask(task_id=task_id, receipt=task_id)

    async def ack(self, item: QueuedTask) -> None:
        self._in_flight.discard(item.task_id)

    async def nack(self, item: QueuedTask) -> None:
        self._in_flight.discard(item.task_id)
        await self._queue.put(item.task_id)

    async def depth(self) -> int:
        return self._queue.qsize()
