"""Engine and session management.

The same models run on PostgreSQL (asyncpg) and on SQLite (aiosqlite).  Postgres
is the target for every deployment mode; SQLite exists so the POC starts on a
laptop with no Docker daemon (section 36, Mode A).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import Settings, get_settings
from core.logging import get_logger
from persistence.models import Base

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _prepare_sqlite_path(url: str) -> None:
    """SQLite will not create the parent directory for us."""
    marker = ":///"
    if marker not in url:
        return
    raw = url.split(marker, 1)[1]
    if raw in ("", ":memory:"):
        return
    Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        if settings.database_url.startswith("sqlite"):
            _prepare_sqlite_path(settings.database_url)
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=not settings.database_url.startswith("sqlite"),
        )
        log.info("database.engine.created", dialect=_engine.dialect.name)
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(settings), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None,
) -> AsyncIterator[AsyncSession]:
    """Transaction boundary: commit on success, roll back on any exception."""
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def create_schema(settings: Settings | None = None) -> None:
    """POC bootstrap.  Production uses the SQL in persistence/migrations."""
    engine = get_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    log.info("database.schema.ready")


async def drop_schema(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
