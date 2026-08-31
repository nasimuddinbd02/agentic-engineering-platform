"""Event bus interface (sections 31, 32 and 57).

Workers publish; every API instance subscribes.  This is why a browser can
reconnect through the load balancer to a different API pod and still see live
progress.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from core.ids import event_id
from core.time import utcnow


@dataclass
class Event:
    task_id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    sequence: int = 0
    id: str = field(default_factory=event_id)
    timestamp: str = field(default_factory=lambda: utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus(ABC):
    @abstractmethod
    async def publish(self, event: Event) -> None: ...

    @abstractmethod
    def subscribe(self, task_id: str) -> AsyncIterator[Event]:
        """Yield events for one task until the consumer stops iterating."""

    async def close(self) -> None:  # pragma: no cover - adapters override
        return None
