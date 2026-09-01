"""Server-Sent Events (section 32).

The stream replays everything already durable in PostgreSQL, then follows the
Redis channel.  A browser can therefore reconnect through the load balancer to a
different API instance and lose nothing (sections 56 and 57).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from apps.api.dependencies import get_coordination, get_task_service
from apps.api.services import TaskService
from core.domain import TERMINAL_STATUSES, WAITING_STATUSES
from core.errors import TaskNotFoundError
from core.logging import get_logger
from infrastructure.events.base import Event

router = APIRouter(prefix="/api/v1/tasks", tags=["events"])
log = get_logger(__name__)

HEARTBEAT_SECONDS = 15.0

#: A stream ends when no worker will act on the task again - either it is
#: terminal, or it is parked waiting for a person (section 30). READY_FOR_REVIEW
#: is the common success case and is not a terminal status.
SETTLED_STATUSES = TERMINAL_STATUSES | WAITING_STATUSES


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
    already_finished = task.status in SETTLED_STATUSES
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
            yield _sse(
                {"type": "STREAM_END", "task_id": task_id, "sequence": highest, "payload": {}}
            )
            return

        # Pump the subscription into a local queue rather than awaiting the
        # generator directly: the heartbeat timeout cancels whatever it is
        # waiting on, and cancelling an async generator's __anext__ leaves the
        # generator unusable. Cancelling a queue.get() is safe, so the stream
        # survives tasks that are quiet for longer than the heartbeat - which
        # is every task that runs a build.
        inbox: asyncio.Queue[Event | None] = asyncio.Queue()

        async def pump() -> None:
            try:
                async for event in events.subscribe(task_id):
                    await inbox.put(event)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("events.subscription_failed", task_id=task_id)
            finally:
                await inbox.put(None)

        pump_task = asyncio.create_task(pump())
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(inbox.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if event is None:
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
                if event.type in (
                    "TASK_COMPLETED",
                    "TASK_FAILED",
                    "TASK_CANCELLED",
                    "APPROVAL_REQUESTED",
                    "NO_PROGRESS_DETECTED",
                ):
                    current = await service.get(task_id)
                    if current.status in SETTLED_STATUSES:
                        yield _sse(
                            {
                                "type": "STREAM_END",
                                "task_id": task_id,
                                "sequence": highest,
                                "payload": {},
                            }
                        )
                        return
        finally:
            pump_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_task

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
