"""Redis pub/sub event bus."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from redis.asyncio import Redis

from core.logging import get_logger
from infrastructure.events.base import Event, EventBus

log = get_logger(__name__)


class RedisEventBus(EventBus):
    def __init__(self, redis: Redis, channel_prefix: str) -> None:
        self.redis = redis
        self.channel_prefix = channel_prefix

    def _channel(self, task_id: str) -> str:
        return f"{self.channel_prefix}:{task_id}"

    async def publish(self, event: Event) -> None:
        await self.redis.publish(self._channel(event.task_id), json.dumps(event.to_dict()))

    async def subscribe(self, task_id: str) -> AsyncIterator[Event]:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self._channel(task_id))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:  # pragma: no cover
                    log.warning("events.decode_failed", task_id=task_id)
                    continue
                yield Event(**payload)
        finally:
            await pubsub.unsubscribe(self._channel(task_id))
            await pubsub.close()
