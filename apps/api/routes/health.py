"""Liveness and readiness (section 29).

``/health/live`` says the process is up; ``/health/ready`` says its dependencies
answer.  Kubernetes needs both to be different things.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text

from apps.api.dependencies import get_coordination, settings_dependency
from apps.api.schemas import HealthOut
from core.config import Settings
from persistence.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthOut)
async def live() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/health/ready", response_model=HealthOut)
async def ready(
    response: Response, settings: Settings = Depends(settings_dependency)
) -> HealthOut:
    checks: dict[str, str] = {}

    try:
        engine = get_engine(settings)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports, never raises
        checks["database"] = f"error: {type(exc).__name__}"

    coordination = get_coordination()
    checks["coordination"] = coordination.backend
    try:
        checks["queue_depth"] = str(await coordination.queue.depth())
    except Exception as exc:  # noqa: BLE001
        checks["queue_depth"] = f"error: {type(exc).__name__}"

    healthy = all(not value.startswith("error") for value in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(status="ok" if healthy else "degraded", checks=checks)
