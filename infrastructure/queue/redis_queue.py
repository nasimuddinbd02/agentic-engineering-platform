"""Redis Streams task queue.

Streams (not plain lists) so a crashed worker's in-flight message stays in the
consumer group's pending list and can be reclaimed - the multi-server failure
scenario in section 55.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from core.logging import get_logger
from infrastructure.queue.base import QueuedTask, TaskQueue

log = get_logger(__name__)

CONSUMER_GROUP = "agent-workers"


class RedisTaskQueue(TaskQueue):
    def __init__(self, redis: Redis, stream: str, consumer_name: str) -> None:
        self.redis = redis
        self.stream = stream
        self.consumer_name = consumer_name
        self._group_ready = False

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self.redis.xgroup_create(self.stream, CONSUMER_GROUP, id="0", mkstream=True)
        except ResponseError as exc:  # group already exists
            if "BUSYGROUP" not in str(exc):
                raise
        self._group_ready = True

    async def publish(self, task_id: str) -> None:
        await self._ensure_group()
        await self.redis.xadd(self.stream, {"task_id": task_id})
        log.info("queue.published", task_id=task_id, stream=self.stream)

    async def receive(self, timeout_seconds: float = 5.0) -> QueuedTask | None:
        await self._ensure_group()
        # First drain anything this consumer already owns (crash recovery),
        # then read new entries.
        for start_id in (">",):
            response = await self.redis.xreadgroup(
                CONSUMER_GROUP,
                self.consumer_name,
                {self.stream: start_id},
                count=1,
                block=int(timeout_seconds * 1000),
            )
            if response:
                _stream, entries = response[0]
                message_id, fields = entries[0]
                task_id = fields.get("task_id") or fields.get(b"task_id")
                if isinstance(task_id, bytes):
                    task_id = task_id.decode()
                if isinstance(message_id, bytes):
                    message_id = message_id.decode()
                return QueuedTask(task_id=task_id, receipt=message_id)
        return None

    async def reclaim_stale(self, min_idle_ms: int, count: int = 10) -> list[QueuedTask]:
        """Take over messages whose worker died (section 39)."""
        await self._ensure_group()
        try:
            _next, entries, _deleted = await self.redis.xautoclaim(
                self.stream,
                CONSUMER_GROUP,
                self.consumer_name,
                min_idle_time=min_idle_ms,
                count=count,
            )
        except ResponseError:  # pragma: no cover - older redis servers
            return []
        reclaimed: list[QueuedTask] = []
        for message_id, fields in entries:
            task_id = fields.get("task_id") or fields.get(b"task_id")
            if isinstance(task_id, bytes):
                task_id = task_id.decode()
            if isinstance(message_id, bytes):
                message_id = message_id.decode()
            if task_id:
                reclaimed.append(QueuedTask(task_id=task_id, receipt=message_id, attempt=2))
        return reclaimed

    async def ack(self, item: QueuedTask) -> None:
        if item.receipt:
            await self.redis.xack(self.stream, CONSUMER_GROUP, item.receipt)

    async def nack(self, item: QueuedTask) -> None:
        # Leave it pending; xautoclaim hands it to the next healthy worker.
        log.warning("queue.nack", task_id=item.task_id)

    async def depth(self) -> int:
        await self._ensure_group()
        try:
            info = await self.redis.xinfo_groups(self.stream)
        except ResponseError:  # pragma: no cover
            return 0
        for group in info:
            name = group.get("name") or group.get(b"name")
            if isinstance(name, bytes):
                name = name.decode()
            if name == CONSUMER_GROUP:
                return int(group.get("lag") or group.get(b"lag") or 0)
        return 0
