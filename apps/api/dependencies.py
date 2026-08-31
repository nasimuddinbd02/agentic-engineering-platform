"""FastAPI dependency wiring.

API instances hold no durable state (section 2.3): every request opens its own
session and uses the shared coordination adapters.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services import TaskService
from core.config import Settings, get_settings
from infrastructure import Coordination, build_coordination
from persistence.db import get_session_factory

_coordination: Coordination | None = None


def get_coordination() -> Coordination:
    global _coordination
    if _coordination is None:
        _coordination = build_coordination(get_settings(), consumer_name="api")
    return _coordination


async def reset_coordination_cache() -> None:
    global _coordination
    _coordination = None


def settings_dependency() -> Settings:
    return get_settings()


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(get_settings())
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_task_service(
    session: AsyncSession = Depends(get_session),
) -> TaskService:
    coordination = get_coordination()
    return TaskService(session, coordination.queue, coordination.events)
