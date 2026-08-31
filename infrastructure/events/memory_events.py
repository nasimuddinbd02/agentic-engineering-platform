"""In-process fan-out event bus (development and tests)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from infrastructure.events.base import Event, EventBus


class MemoryEventBus(EventBus):
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Event]]] = {}

    async def publish(self, event: Event) -> None:
        for queue in list(self._subscribers.get(event.task_id, ())):
            queue.put_nowait(event)

    async def subscribe(self, task_id: str) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.setdefault(task_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            subscribers = self._subscribers.get(task_id)
            if subscribers:
                subscribers.discard(queue)
                if not subscribers:
                    self._subscribers.pop(task_id, None)
