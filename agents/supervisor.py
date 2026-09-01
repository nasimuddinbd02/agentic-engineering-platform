"""Supervisor (section 9).

Not the smartest agent - the workflow controller.  It wraps every node with the
same discipline: set the task status, open an agent_run, run the node, persist
the checkpoint, publish events, and convert failures into routing decisions
instead of crashes (section 51).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.domain import NODE_STATUS, EventType, TaskStatus
from core.errors import (
    PolicyViolationError,
    TransientInfrastructureError,
    WorkspaceViolationError,
)
from core.logging import get_logger
from graph.context import WorkflowContext
from graph.state import AgentState

log = get_logger(__name__)

NodeFunction = Callable[[AgentState], Awaitable[dict[str, Any]]]

#: node -> the agent whose allowlist and prompt it uses.
NODE_AGENT = {
    "plan": "planner",
    "repository_analysis": "repository",
    "risk_assessment": "risk",
    "implementation": "implementation",
    "test_generation": "testing",
    "run_tests": "supervisor",
    "debugging": "debugging",
    "security_policy": "supervisor",
    "git_commit": "supervisor",
    "ci_validation": "supervisor",
    "ci_debugging": "ci",
    "create_pr": "supervisor",
    "human_review": "supervisor",
    "halt": "supervisor",
}


class Supervisor:
    def __init__(self, context: WorkflowContext) -> None:
        self.context = context

    def instrument(self, node_name: str, function: NodeFunction) -> NodeFunction:
        """Wrap a node with status, audit, checkpointing and error routing."""

        async def wrapped(state: AgentState) -> dict[str, Any]:
            agent = NODE_AGENT.get(node_name, "supervisor")
            iteration = state.get("iteration", 0)
            await self.context.emit(EventType.NODE_STARTED, node=node_name, agent=agent)

            status = NODE_STATUS.get(node_name, TaskStatus.PLANNING)
            merged: dict[str, Any] = {}
            run_id = await self.context.start_agent_run(node_name, agent, iteration)
            self.context.current_agent_run_id = run_id
            await self.context.save_checkpoint(dict(state), node=node_name, status=status)

            try:
                update = await function(state) or {}
                usage = update.pop("_usage", None)
                merged = {key: value for key, value in update.items() if not key.startswith("_")}
                await self.context.finish_agent_run(run_id, status="COMPLETED", usage=usage)
                if usage is not None:
                    self.context.usage = self.context.usage.merge(usage)
            except (PolicyViolationError, WorkspaceViolationError) as exc:
                # A hard boundary was hit: stop the task, do not retry (section 51).
                log.warning("node.blocked", node=node_name, error=str(exc))
                await self.context.finish_agent_run(run_id, status="BLOCKED", error=str(exc))
                merged = {
                    "halt_reason": str(exc),
                    "policy_action": "BLOCK",
                    "error": str(exc),
                }
            except TransientInfrastructureError as exc:
                log.warning("node.transient_failure", node=node_name, error=str(exc))
                await self.context.finish_agent_run(run_id, status="FAILED", error=str(exc))
                merged = {
                    "halt_reason": f"infrastructure error in {node_name}: {exc}",
                    "error": str(exc),
                }
            # One failing node must not kill the worker; it becomes a routing
            # decision instead (section 51).
            except Exception as exc:
                log.exception("node.failed", node=node_name)
                await self.context.finish_agent_run(run_id, status="FAILED", error=str(exc))
                merged = {
                    "halt_reason": f"{node_name} failed: {type(exc).__name__}: {exc}",
                    "error": str(exc),
                }
            finally:
                self.context.current_agent_run_id = None

            checkpoint = {**state, **merged}
            await self.context.save_checkpoint(checkpoint, node=node_name, status=status)
            await self.context.emit(
                EventType.NODE_COMPLETED, node=node_name, keys=sorted(merged)[:12]
            )
            return merged

        wrapped.__name__ = f"{node_name}_node"
        return wrapped
