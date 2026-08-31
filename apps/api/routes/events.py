"""Server-Sent Events (section 32).

The stream replays everything already durable in PostgreSQL, then follows the
Redis channel.  A browser can therefore reconnect through the load balancer to a
different API instance and lose nothing (sections 56 and 57).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from apps.api.dependencies import get_coordination, get_task_service
from apps.api.services import TaskService
from core.domain import TERMINAL_STATUSES
from core.errors import TaskNotFoundError
from core.logging import get_logger

router = APIRouter(prefix="/api/v1/tasks", tags=["events"])
log = get_logger(__name__)

HEARTBEAT_SECONDS = 15.0


def _sse(payload: dict) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"


@router.get("/{task_id}/events")
async def stream_events(
    task_id: str,
    request: Request,
    last_event_sequence: int = Query(default=0, alias="after"),
    service: TaskService = Depends(get_task_service),
) -> StreamingResponse:
    try:
        replay = await service.events_since(task_id, after_sequence=last_event_sequence)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc

    task = await service.get(task_id)
    already_finished = task.status in TERMINAL_STATUSES
    events = get_coordination().events

    async def generator() -> AsyncIterator[str]:
        highest = last_event_sequence
        for event in replay:
            highest = max(highest, event.sequence)
            yield _sse(
                {
                    "id": event.id,
                    "task_id": task_id,
                    "type": event.type,
                    "sequence": event.sequence,
                    "payload": event.payload or {},
                    "timestamp": event.created_at.isoformat(),
                }
            )
        if already_finished:
            yield _sse({"type": "STREAM_END", "task_id": task_id, "sequence": highest, "payload": {}})
            return

        subscription = events.subscribe(task_id).__aiter__()
        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(
                    subscription.__anext__(), timeout=HEARTBEAT_SECONDS
                )
            except (TimeoutError, asyncio.TimeoutError):
                yield ": heartbeat\n\n"
                continue
            except StopAsyncIteration:  # pragma: no cover - bus closed
                return

            if event.sequence and event.sequence <= highest:
                continue
            highest = max(highest, event.sequence)
            yield _sse(
                {
                    "id": event.id,
                    "task_id": event.task_id,
                    "type": event.type,
                    "sequence": event.sequence,
                    "payload": event.payload,
                    "timestamp": event.timestamp,
                }
            )
            if event.type in ("TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED", "APPROVAL_REQUESTED"):
                current = await service.get(task_id)
                if current.status in TERMINAL_STATUSES:
                    yield _sse(
                        {"type": "STREAM_END", "task_id": task_id, "sequence": highest, "payload": {}}
                    )
                    return

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
