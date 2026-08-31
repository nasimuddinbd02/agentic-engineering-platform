"""Task endpoints (sections 15, 29 and 52)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Response, status

from apps.api.dependencies import get_task_service, settings_dependency
from apps.api.schemas import (
    AgentRunOut,
    ApprovalOut,
    CIRunOut,
    CreateTaskRequest,
    DecisionRequest,
    EventOut,
    FileChangeOut,
    TaskAccepted,
    TaskDetail,
    TaskSummary,
    ToolCallOut,
)
from apps.api.services import TaskService
from core.config import Settings
from core.errors import InvalidTaskTransitionError, TaskNotFoundError

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("", response_model=TaskAccepted, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: CreateTaskRequest,
    response: Response,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    service: TaskService = Depends(get_task_service),
    settings: Settings = Depends(settings_dependency),
) -> TaskAccepted:
    """Persist the task, then queue it. The agent never runs in this handler."""
    try:
        task, created = await service.create_task(
            repository_url=request.repository,
            repository_path=request.repository_path,
            issue=request.issue,
            created_by=request.created_by,
            idempotency_key=idempotency_key,
        )
    except InvalidTaskTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if created:
        # Enqueue after the response transaction commits, so a worker can never
        # claim a task that is not yet visible in PostgreSQL.
        background.add_task(service.enqueue, task.id)
    else:
        response.status_code = status.HTTP_200_OK

    return TaskAccepted(task_id=task.id, status=task.status)


@router.get("", response_model=list[TaskSummary])
async def list_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    task_status: str | None = Query(default=None, alias="status"),
    service: TaskService = Depends(get_task_service),
) -> list[TaskSummary]:
    return [TaskSummary.of(task) for task in await service.list(limit=limit, status=task_status)]


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str, service: TaskService = Depends(get_task_service)) -> TaskDetail:
    try:
        detail = await service.detail(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc
    return TaskDetail(
        task=TaskSummary.of(detail["task"]),
        events=[EventOut.of(event) for event in detail["events"]],
        runs=[AgentRunOut.of(run) for run in detail["runs"]],
        tool_calls=[ToolCallOut.of(call) for call in detail["tool_calls"]],
        file_changes=[FileChangeOut.of(change) for change in detail["file_changes"]],
        ci_runs=[CIRunOut.of(run) for run in detail["ci_runs"]],
        approvals=[ApprovalOut.of(approval) for approval in detail["approvals"]],
    )


@router.get("/{task_id}/diff", response_class=Response)
async def get_diff(task_id: str, service: TaskService = Depends(get_task_service)) -> Response:
    try:
        diff = await service.diff(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc
    return Response(content=diff, media_type="text/plain; charset=utf-8")


@router.get("/{task_id}/logs", response_model=list[ToolCallOut])
async def get_logs(task_id: str, service: TaskService = Depends(get_task_service)) -> list[ToolCallOut]:
    try:
        detail = await service.detail(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc
    return [ToolCallOut.of(call) for call in detail["tool_calls"]]


@router.post("/{task_id}/approve", response_model=TaskSummary)
async def approve(
    task_id: str,
    request: DecisionRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskSummary:
    try:
        task = await service.approve(task_id, decided_by=request.decided_by, reason=request.reason)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc
    except InvalidTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskSummary.of(task)


@router.post("/{task_id}/reject", response_model=TaskSummary)
async def reject(
    task_id: str,
    request: DecisionRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskSummary:
    try:
        task = await service.reject(task_id, decided_by=request.decided_by, reason=request.reason)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc
    except InvalidTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskSummary.of(task)


@router.post("/{task_id}/cancel", response_model=TaskSummary)
async def cancel(
    task_id: str,
    request: DecisionRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskSummary:
    try:
        task = await service.cancel(task_id, reason=request.reason)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found") from exc
    except InvalidTaskTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TaskSummary.of(task)
