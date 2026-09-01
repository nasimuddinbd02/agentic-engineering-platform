"""Redis lock: SET NX PX to acquire, owner-checked Lua scripts to renew/release."""

from __future__ import annotations

from redis.asyncio import Redis

from infrastructure.locks.base import LockManager

_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisLockManager(LockManager):
    def __init__(self, redis: Redis, prefix: str = "agent:lock") -> None:
        self.redis = redis
        self.prefix = prefix

    def _key(self, name: str) -> str:
        return f"{self.prefix}:{name}"

    async def acquire(self, name: str, ttl_seconds: int, owner: str) -> bool:
        return bool(await self.redis.set(self._key(name), owner, nx=True, px=ttl_seconds * 1000))

    async def renew(self, name: str, ttl_seconds: int, owner: str) -> bool:
        result = await self.redis.eval(_RENEW, 1, self._key(name), owner, str(ttl_seconds * 1000))
        return bool(result)

    async def release(self, name: str, owner: str) -> None:
        await self.redis.eval(_RELEASE, 1, self._key(name), owner)
