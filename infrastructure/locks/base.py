"""Distributed lock interface (section 17).

Two workers must never execute the same task.  This is the fast half of the
guard; ``TaskRepository.claim`` is the durable half.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator


class LockManager(ABC):
    @abstractmethod
    async def acquire(self, name: str, ttl_seconds: int, owner: str) -> bool: ...

    @abstractmethod
    async def renew(self, name: str, ttl_seconds: int, owner: str) -> bool: ...

    @abstractmethod
    async def release(self, name: str, owner: str) -> None: ...

    @asynccontextmanager
    async def hold(self, name: str, ttl_seconds: int, owner: str) -> AsyncIterator[bool]:
        acquired = await self.acquire(name, ttl_seconds, owner)
        try:
            yield acquired
        finally:
            if acquired:
                await self.release(name, owner)
