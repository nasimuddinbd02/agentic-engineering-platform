"""Executing one task (sections 15, 39 and 55).

Claim the lease, rebuild the context, run the graph, persist the outcome.  The
workspace is local to this worker and disposable; everything that matters is in
PostgreSQL, so another worker can restart the task from the last checkpoint.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.errors import GraphRecursionError

from core.config import Settings
from core.domain import TERMINAL_STATUSES, EventType, TaskStatus
from core.errors import AgentPlatformError
from core.ids import run_id
from core.logging import bind_task, clear_task_context, get_logger
from graph.context import WorkflowContext
from graph.state import AgentState, initial_state, summarize
from graph.workflow import RECURSION_LIMIT, build_workflow
from infrastructure import Coordination
from llm.factory import build_llm_provider
from persistence.db import session_scope
from persistence.repositories import TaskRepository
from policies.evaluator import get_policy_engine
from providers.factory import build_ci_provider, build_scm_provider
from tools.registry import ToolRegistry
from tools.workspace import WorkspaceManager

log = get_logger(__name__)


class TaskExecutor:
    def __init__(
        self,
        settings: Settings,
        coordination: Coordination,
        worker_id: str,
        workspaces: WorkspaceManager | None = None,
    ) -> None:
        self.settings = settings
        self.coordination = coordination
        self.worker_id = worker_id
        self.workspaces = workspaces or WorkspaceManager(
            settings.workspace_root, settings.command_timeout_seconds
        )
        self.tools = ToolRegistry(settings)

    async def execute(self, task_id: str) -> dict[str, Any]:
        """Run one task end to end. Returns the section 45 result summary."""
        bind_task(task_id, worker=self.worker_id)
        try:
            return await self._execute(task_id)
        finally:
            clear_task_context()

    async def _execute(self, task_id: str) -> dict[str, Any]:
        # Fast lock first (section 17), durable lease second.
        lock_name = f"task:{task_id}"
        acquired = await self.coordination.locks.acquire(
            lock_name, self.settings.task_lease_seconds, self.worker_id
        )
        if not acquired:
            log.info("task.already_locked", task_id=task_id)
            return {"task_id": task_id, "skipped": "locked by another worker"}

        try:
            async with session_scope(self.settings) as session:
                repository = TaskRepository(session)
                task = await repository.get(task_id)
                if task is None:
                    log.warning("task.missing", task_id=task_id)
                    return {"task_id": task_id, "skipped": "not found"}
                if task.status in TERMINAL_STATUSES:
                    return {"task_id": task_id, "skipped": f"already {task.status}"}
                claimed = await repository.claim(
                    task_id, self.worker_id, self.settings.task_lease_seconds
                )
                if claimed is None:
                    return {"task_id": task_id, "skipped": "lease held elsewhere"}
                snapshot = {
                    "repository_url": task.repository_url,
                    "repository_path": task.repository_path,
                    "issue": task.issue,
                    "state": dict(task.state or {}),
                    "workspace_path": task.workspace_path,
                    "branch": task.branch,
                }

            return await self._run_workflow(task_id, snapshot)
        finally:
            await self.coordination.locks.release(lock_name, self.worker_id)
            async with session_scope(self.settings) as session:
                await TaskRepository(session).release(task_id, self.worker_id)

    async def _run_workflow(self, task_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        try:
            repository_path = self._resolve_repository_path(snapshot)
        except AgentPlatformError as exc:
            # A bad repository path is a configuration error, not a transient
            # one (section 51). Retrying it forever would be a sweep loop, so
            # the task terminates here.
            log.error("task.bad_repository_path", task_id=task_id, error=str(exc))
            await self._finalize_failure(task_id, str(exc))
            return {"task_id": task_id, "status": TaskStatus.FAILED.value, "error": str(exc)}

        workflow_run_id = run_id()

        context = WorkflowContext(
            settings=self.settings,
            llm=build_llm_provider(self.settings),
            tools=self.tools,
            workspaces=self.workspaces,
            policy=get_policy_engine(),
            scm=build_scm_provider(self.settings),
            ci=build_ci_provider(self.settings),
            events=self.coordination.events,
            task_id=task_id,
            workflow_run_id=workflow_run_id,
        )

        state: AgentState = initial_state(
            task_id=task_id,
            workflow_run_id=workflow_run_id,
            repository_url=snapshot["repository_url"],
            repository_path=str(repository_path),
            issue=snapshot["issue"],
            max_iterations=self.settings.max_agent_iterations,
            max_ci_iterations=self.settings.max_ci_iterations,
        )
        state["max_files"] = self.settings.max_files_per_task
        # Resume from the checkpoint if a previous worker got part way (section 55).
        previous = snapshot.get("state") or {}
        if previous:
            state.update({key: value for key, value in previous.items() if value is not None})
            state["workflow_run_id"] = workflow_run_id
        if snapshot.get("workspace_path") and snapshot.get("branch"):
            existing = Path(snapshot["workspace_path"])
            if existing.is_dir():
                await self.workspaces.adopt(task_id, existing, snapshot["branch"], repository_path)

        await context.emit(
            EventType.TASK_CLAIMED, worker=self.worker_id, workflow_run_id=workflow_run_id
        )

        try:
            workflow = build_workflow(context)
            final_state = await workflow.ainvoke(state, config={"recursion_limit": RECURSION_LIMIT})
        except GraphRecursionError as exc:
            # The state-based bounds should stop the loops long before this; if
            # the backstop fires it is a routing bug, so escalate rather than
            # fail silently.
            log.error("workflow.recursion_limit", task_id=task_id, limit=RECURSION_LIMIT)
            await context.emit(
                EventType.NO_PROGRESS_DETECTED, reason="graph recursion limit reached"
            )
            result = await self._finalize(
                task_id,
                {
                    **state,
                    "outcome": "HUMAN_REVIEW_REQUIRED",
                    "halt_reason": f"graph recursion limit ({RECURSION_LIMIT}) reached: {exc}",
                },
            )
            await context.close()
            return result
        # The task fails; the worker lives to take the next one.
        except Exception as exc:
            log.exception("workflow.failed", task_id=task_id)
            await self._finalize_failure(task_id, str(exc))
            await context.emit(EventType.TASK_FAILED, error=str(exc))
            await context.close()
            return {"task_id": task_id, "status": TaskStatus.FAILED.value, "error": str(exc)}

        result = await self._finalize(task_id, final_state)
        await context.close()
        return result

    def _resolve_repository_path(self, snapshot: dict[str, Any]) -> Path:
        raw = snapshot.get("repository_path") or snapshot.get("repository_url", "")
        path = Path(str(raw)).expanduser()
        if not path.is_dir():
            raise AgentPlatformError(
                f"repository_path does not exist on this worker: {raw}. "
                "The POC works against a local checkout; clone it first."
            )
        return path.resolve()

    async def _finalize(self, task_id: str, state: dict[str, Any]) -> dict[str, Any]:
        outcome = state.get("outcome", "")
        if outcome == "HUMAN_REVIEW_REQUIRED":
            status = TaskStatus.HUMAN_REVIEW_REQUIRED
        elif outcome == "READY_FOR_REVIEW":
            status = TaskStatus.READY_FOR_REVIEW
        else:
            status = TaskStatus.FAILED

        async with session_scope(self.settings) as session:
            repository = TaskRepository(session)
            await repository.save_state(task_id, dict(state))
            await repository.set_status(
                task_id, status, node=None, error=state.get("halt_reason") or None
            )

        summary = summarize(state)  # type: ignore[arg-type]
        summary["status"] = status.value
        log.info(
            "task.finished",
            task_id=task_id,
            status=status.value,
            files=len(summary.get("files_changed", [])),
            iterations=summary.get("iterations"),
        )
        return summary

    async def _finalize_failure(self, task_id: str, error: str) -> None:
        async with session_scope(self.settings) as session:
            await TaskRepository(session).set_status(task_id, TaskStatus.FAILED, error=error)
