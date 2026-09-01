"""SQLAlchemy models - the durable audit system of section 58."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.domain import TaskStatus
from persistence.models.base import Base, TimestampMixin
from persistence.models.types import Embedding, JsonDict, JsonList, UtcDateTime

__all__ = [
    "AgentRun",
    "Approval",
    "Base",
    "CIRun",
    "CodeChunk",
    "EvaluationResult",
    "FileChange",
    "IdempotencyRecord",
    "Repository",
    "Task",
    "TaskEvent",
    "ToolCall",
]


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_url: Mapped[str] = mapped_column(Text, nullable=False)
    repository_path: Mapped[str | None] = mapped_column(Text)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(48), nullable=False, default=TaskStatus.QUEUED, index=True
    )
    risk_level: Mapped[str | None] = mapped_column(String(16))
    current_node: Mapped[str | None] = mapped_column(String(64))
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ci_iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    workspace_path: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(String(255))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    pull_request_url: Mapped[str | None] = mapped_column(Text)

    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True)

    #: Full AgentState snapshot so another worker can resume (sections 2.4 and 55).
    state: Mapped[dict] = mapped_column(JsonDict, default=dict)
    summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    #: Lease held by the worker currently executing this task (section 17).
    locked_by: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)

    events: Mapped[list[TaskEvent]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin"
    )


class AgentRun(Base, TimestampMixin):
    """One execution of one workflow node."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    workflow_run_id: Mapped[str] = mapped_column(String(64), index=True)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)


class ToolCall(Base, TimestampMixin):
    """Every tool invocation, for the audit questions in section 58."""

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    agent_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict] = mapped_column(JsonDict, default=dict)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    result_preview: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class TaskEvent(Base):
    """Append-only timeline (section 31). Also mirrored to Redis for the live UI."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, index=True)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JsonDict, default=dict)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    task: Mapped[Task] = relationship(back_populates="events")

    __table_args__ = (Index("ix_task_events_task_seq", "task_id", "sequence"),)


class FileChange(Base, TimestampMixin):
    __tablename__ = "file_changes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(16), default="MODIFIED")
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, default=0)
    diff: Mapped[str | None] = mapped_column(Text)


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    reason: Mapped[str | None] = mapped_column(Text)
    requested_reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(String(255))
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class CIRun(Base, TimestampMixin):
    __tablename__ = "ci_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128))
    branch: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    conclusion: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[str | None] = mapped_column(Text)
    iteration: Mapped[int] = mapped_column(Integer, default=0)


class EvaluationResult(Base, TimestampMixin):
    """One benchmark fixture run (sections 42 and 48)."""

    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fixture: Mapped[str] = mapped_column(String(128), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64))
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    metrics: Mapped[dict] = mapped_column(JsonDict, default=dict)
    details: Mapped[dict] = mapped_column(JsonDict, default=dict)


class Repository(Base, TimestampMixin):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    languages: Mapped[list] = mapped_column(JsonList, default=list)
    indexed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("url", name="uq_repositories_url"),)


class CodeChunk(Base, TimestampMixin):
    """RAG unit (section 13). ``embedding`` stays null until phase 9 indexing runs."""

    __tablename__ = "code_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repository_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    symbol_name: Mapped[str | None] = mapped_column(String(255), index=True)
    symbol_kind: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(32))
    start_line: Mapped[int] = mapped_column(Integer, default=0)
    end_line: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Embedding)
    meta: Mapped[dict] = mapped_column(JsonDict, default=dict)


class IdempotencyRecord(Base, TimestampMixin):
    """Section 52 - the same Idempotency-Key must map to the same task."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
