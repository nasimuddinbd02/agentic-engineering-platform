"""Task queue interface (section 14).

The queue carries task ids only - never task payloads.  Durable state lives in
PostgreSQL, so a worker always reloads the task before executing it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class QueuedTask:
    task_id: str
    #: Opaque handle the worker must return on ack (Redis stream message id).
    receipt: str | None = None
    attempt: int = 1


class TaskQueue(ABC):
    @abstractmethod
    async def publish(self, task_id: str) -> None: ...

    @abstractmethod
    async def receive(self, timeout_seconds: float = 5.0) -> QueuedTask | None:
        """Block up to ``timeout_seconds`` for one task, or return None."""

    @abstractmethod
    async def ack(self, item: QueuedTask) -> None:
        """Confirm the task will not be redelivered."""

    @abstractmethod
    async def nack(self, item: QueuedTask) -> None:
        """Return the task to the queue for another worker."""

    @abstractmethod
    async def depth(self) -> int: ...

    async def close(self) -> None:  # pragma: no cover - adapters override
        return None
