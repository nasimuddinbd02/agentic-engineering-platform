"""Approval queue (section 24).

The approve/reject actions live on the task routes; this endpoint is the
reviewer's inbox: everything currently waiting on a person.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.dependencies import get_task_service
from apps.api.schemas import TaskSummary
from apps.api.services import TaskService
from core.domain import TaskStatus

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


@router.get("", response_model=list[TaskSummary])
async def pending(service: TaskService = Depends(get_task_service)) -> list[TaskSummary]:
    waiting: list[TaskSummary] = []
    for status in (TaskStatus.READY_FOR_REVIEW, TaskStatus.HUMAN_REVIEW_REQUIRED):
        waiting.extend(
            TaskSummary.of(task) for task in await service.list(limit=100, status=status.value)
        )
    waiting.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
    return waiting
