"""API request and response models (section 29)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from persistence.models import (
    AgentRun,
    Approval,
    CIRun,
    FileChange,
    Task,
    TaskEvent,
    ToolCall,
)


class CreateTaskRequest(BaseModel):
    repository: str = Field(description="Repository URL or identifier.")
    repository_path: str | None = Field(
        default=None, description="Local path to the checkout the agent should work from."
    )
    issue: str = Field(min_length=8, description="The engineering issue to solve.")
    created_by: str | None = None


class TaskAccepted(BaseModel):
    task_id: str
    status: str


class TaskSummary(BaseModel):
    task_id: str
    status: str
    issue: str
    repository_url: str
    risk_level: str | None = None
    current_node: str | None = None
    iteration: int = 0
    approval_required: bool = False
    branch: str | None = None
    commit_sha: str | None = None
    pull_request_url: str | None = None
    summary: str | None = None
    error: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    ci_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def of(cls, task: Task) -> TaskSummary:
        state: dict[str, Any] = task.state or {}
        return cls(
            task_id=task.id,
            status=task.status,
            issue=task.issue,
            repository_url=task.repository_url,
            risk_level=task.risk_level,
            current_node=task.current_node,
            iteration=task.iteration,
            approval_required=task.approval_required,
            branch=task.branch,
            commit_sha=task.commit_sha,
            pull_request_url=task.pull_request_url,
            summary=task.summary,
            error=task.error,
            files_changed=list(state.get("modified_files", [])),
            tests_passed=int(state.get("tests_passed", 0)),
            tests_failed=int(state.get("tests_failed", 0)),
            ci_status=state.get("ci_status") or None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class EventOut(BaseModel):
    id: str
    sequence: int
    type: str
    payload: dict[str, Any]
    timestamp: datetime

    @classmethod
    def of(cls, event: TaskEvent) -> EventOut:
        return cls(
            id=event.id,
            sequence=event.sequence,
            type=event.type,
            payload=event.payload or {},
            timestamp=event.created_at,
        )


class AgentRunOut(BaseModel):
    node: str
    agent: str
    status: str
    iteration: int
    duration_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None

    @classmethod
    def of(cls, run: AgentRun) -> AgentRunOut:
        return cls(
            node=run.node,
            agent=run.agent,
            status=run.status,
            iteration=run.iteration,
            duration_ms=run.duration_ms,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=run.cost_usd,
            error=run.error,
        )


class ToolCallOut(BaseModel):
    tool: str
    ok: bool
    arguments: dict[str, Any]
    duration_ms: int | None = None
    error: str | None = None

    @classmethod
    def of(cls, call: ToolCall) -> ToolCallOut:
        return cls(
            tool=call.tool,
            ok=call.ok,
            arguments=call.arguments or {},
            duration_ms=call.duration_ms,
            error=call.error,
        )


class FileChangeOut(BaseModel):
    path: str
    change_type: str
    iteration: int
    lines_added: int
    lines_removed: int

    @classmethod
    def of(cls, change: FileChange) -> FileChangeOut:
        return cls(
            path=change.path,
            change_type=change.change_type,
            iteration=change.iteration,
            lines_added=change.lines_added,
            lines_removed=change.lines_removed,
        )


class CIRunOut(BaseModel):
    provider: str
    status: str
    url: str | None = None
    iteration: int = 0

    @classmethod
    def of(cls, run: CIRun) -> CIRunOut:
        return cls(provider=run.provider, status=run.status, url=run.url, iteration=run.iteration)


class ApprovalOut(BaseModel):
    id: str
    status: str
    requested_reason: str | None = None
    decided_by: str | None = None
    reason: str | None = None

    @classmethod
    def of(cls, approval: Approval) -> ApprovalOut:
        return cls(
            id=approval.id,
            status=approval.status,
            requested_reason=approval.requested_reason,
            decided_by=approval.decided_by,
            reason=approval.reason,
        )


class TaskDetail(BaseModel):
    task: TaskSummary
    events: list[EventOut]
    runs: list[AgentRunOut]
    tool_calls: list[ToolCallOut]
    file_changes: list[FileChangeOut]
    ci_runs: list[CIRunOut]
    approvals: list[ApprovalOut]


class DecisionRequest(BaseModel):
    decided_by: str | None = None
    reason: str | None = None


class IndexRepositoryRequest(BaseModel):
    url: str
    path: str
    default_branch: str = "main"


class RepositoryOut(BaseModel):
    id: str
    url: str
    path: str
    default_branch: str
    chunk_count: int
    indexed_at: datetime | None = None


class HealthOut(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
