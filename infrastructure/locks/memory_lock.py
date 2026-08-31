"""In-process lock manager with the same TTL semantics as the Redis one."""

from __future__ import annotations

import time

from infrastructure.locks.base import LockManager


class MemoryLockManager(LockManager):
    def __init__(self) -> None:
        self._locks: dict[str, tuple[str, float]] = {}

    def _live(self, name: str) -> tuple[str, float] | None:
        entry = self._locks.get(name)
        if entry and entry[1] > time.monotonic():
            return entry
        if entry:
            self._locks.pop(name, None)
        return None

    async def acquire(self, name: str, ttl_seconds: int, owner: str) -> bool:
        if self._live(name):
            return False
        self._locks[name] = (owner, time.monotonic() + ttl_seconds)
        return True

    async def renew(self, name: str, ttl_seconds: int, owner: str) -> bool:
        entry = self._live(name)
        if not entry or entry[0] != owner:
            return False
        self._locks[name] = (owner, time.monotonic() + ttl_seconds)
        return True

    async def release(self, name: str, owner: str) -> None:
        entry = self._locks.get(name)
        if entry and entry[0] == owner:
            self._locks.pop(name, None)
