"""Infrastructure composition root.

One place decides which adapter backs each interface, so no application or agent
code ever imports ``redis`` directly (rule 7 of section 61).
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

from core.config import Settings, get_settings
from core.ids import new_id
from core.logging import get_logger
from infrastructure.events.base import EventBus
from infrastructure.events.memory_events import MemoryEventBus
from infrastructure.locks.base import LockManager
from infrastructure.locks.memory_lock import MemoryLockManager
from infrastructure.queue.base import TaskQueue
from infrastructure.queue.memory_queue import MemoryTaskQueue

log = get_logger(__name__)

#: Memory adapters must be shared across every consumer inside one process.
_memory_queue: MemoryTaskQueue | None = None
_memory_events: MemoryEventBus | None = None
_memory_locks: MemoryLockManager | None = None
_redis_client: Any | None = None


def worker_identity(prefix: str = "worker") -> str:
    """Stable-ish identity used for leases and consumer names."""
    return f"{prefix}-{socket.gethostname()}-{new_id('w').split('-')[1]}"


def get_redis(settings: Settings | None = None) -> Any:
    """Lazily build the shared Redis client (never imported when memory:// is used)."""
    global _redis_client
    settings = settings or get_settings()
    if settings.uses_memory_backend:
        raise RuntimeError("REDIS_URL is memory:// - no Redis client available")
    if _redis_client is None:
        from redis.asyncio import Redis

        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        log.info("redis.client.created", url=settings.redis_url)
    return _redis_client


@dataclass
class Coordination:
    """The three Redis responsibilities, resolved to concrete adapters."""

    queue: TaskQueue
    events: EventBus
    locks: LockManager
    backend: str

    async def close(self) -> None:
        await self.queue.close()
        await self.events.close()


def build_coordination(
    settings: Settings | None = None, *, consumer_name: str | None = None
) -> Coordination:
    global _memory_queue, _memory_events, _memory_locks
    settings = settings or get_settings()

    if settings.uses_memory_backend:
        if _memory_queue is None:
            _memory_queue = MemoryTaskQueue()
        if _memory_events is None:
            _memory_events = MemoryEventBus()
        if _memory_locks is None:
            _memory_locks = MemoryLockManager()
        return Coordination(
            queue=_memory_queue, events=_memory_events, locks=_memory_locks, backend="memory"
        )

    from infrastructure.events.redis_events import RedisEventBus
    from infrastructure.locks.redis_lock import RedisLockManager
    from infrastructure.queue.redis_queue import RedisTaskQueue

    redis = get_redis(settings)
    return Coordination(
        queue=RedisTaskQueue(redis, settings.queue_name, consumer_name or worker_identity("api")),
        events=RedisEventBus(redis, settings.event_channel_prefix),
        locks=RedisLockManager(redis),
        backend="redis",
    )


async def reset_coordination() -> None:
    """Test helper - drop cached adapters."""
    global _memory_queue, _memory_events, _memory_locks, _redis_client
    _memory_queue = None
    _memory_events = None
    _memory_locks = None
    if _redis_client is not None:
        await _redis_client.aclose()
    _redis_client = None
