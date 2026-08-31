"""FastAPI application.

Stateless by construction (section 2.3): no task registry, no connection
registry, nothing in module scope that a second API instance would not have.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.dependencies import get_coordination
from apps.api.routes import approvals, events, health, repositories, tasks
from core.config import get_settings
from core.logging import configure_logging, get_logger
from persistence.db import create_schema, dispose_engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    await create_schema(settings)
    coordination = get_coordination()
    log.info(
        "api.started",
        backend=coordination.backend,
        database=settings.database_url.split("://", 1)[0],
        llm=settings.llm_provider,
        scm=settings.scm_provider,
        ci=settings.ci_provider,
    )
    yield
    await coordination.close()
    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(
        title="AI Software Engineering Agent",
        version="0.1.0",
        summary="An engineering control plane around a coding-capable LLM.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health.router)
    application.include_router(tasks.router)
    application.include_router(events.router)
    application.include_router(approvals.router)
    application.include_router(repositories.router)
    return application


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app", host="0.0.0.0", port=settings.api_port, reload=False
    )
