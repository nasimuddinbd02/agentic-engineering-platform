"""Workflow nodes (section 8).

Each node is a small, testable async function.  Reasoning is delegated to an
agent; anything with a real side effect - creating the worktree, running the
suite, committing, pushing, opening the PR - is executed by the platform itself
so the signal cannot be hallucinated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.ci_agent import CIAgent
from agents.debugging_agent import DebuggingAgent
from agents.git_agent import commit_changes, open_pull_request
from agents.implementation_agent import ImplementationAgent
from agents.planner import PlannerAgent
from agents.repository_agent import RepositoryAgent
from agents.risk_agent import RiskAgent
from agents.testing_agent import TestingAgent
from core.domain import EventType, PolicyAction, RiskLevel, max_risk
from core.errors import AgentPlatformError
from core.logging import get_logger
from graph.context import WorkflowContext
from graph.fingerprint import signatures_for
from graph.routing import halt_reason
from graph.state import AgentState
from providers.ci.base import CIStatus
from tools.base import ToolContext
from tools.git.diff import collect_diff
from tools.testing.test import detect_project_kind, parse_dotnet_output, run_dotnet_test

log = get_logger(__name__)


class Nodes:
    """All workflow nodes, bound to one execution context."""

    def __init__(self, context: WorkflowContext) -> None:
        self.context = context

    # ------------------------------------------------------------- helpers

    def _tool_context(self, state: AgentState, *, in_workspace: bool) -> ToolContext:
        workspace = (
            self.context.workspaces.try_get(state["task_id"]) if in_workspace else None
        )
        return ToolContext(
            task_id=state["task_id"],
            repository_path=Path(state["repository_path"]),
            workspace=workspace,
            iteration=state.get("iteration", 0),
            agent_run_id=self.context.current_agent_run_id,
            write_allowed=state.get("policy_action") != PolicyAction.BLOCK.value,
        )

    def _workspace_path(self, state: AgentState) -> Path:
        workspace = self.context.workspaces.get(state["task_id"])
        return workspace.path

    async def _refresh_diff(self, state: AgentState) -> dict[str, Any]:
        workspace = self.context.workspaces.try_get(state["task_id"])
        if workspace is None:
            return {}
        summary = await collect_diff(workspace.path)
        return {
            "git_diff": summary.diff,
            "modified_files": summary.files,
            "lines_added": summary.insertions,
            "lines_removed": summary.deletions,
        }

    # --------------------------------------------------------------- nodes

    async def plan(self, state: AgentState) -> dict[str, Any]:
        agent = PlannerAgent(self.context)
        result = await agent.plan(state, self._tool_context(state, in_workspace=False))
        await self.context.emit(
            EventType.PLAN_CREATED,
            summary=result.get("plan_summary", ""),
            steps=len(result.get("plan", [])),
        )
        return result

    async def repository_analysis(self, state: AgentState) -> dict[str, Any]:
        """Reads the developer's repository, never writes to it (rule 9)."""
        agent = RepositoryAgent(self.context)
        result = await agent.analyze(state, self._tool_context(state, in_workspace=False))
        await self.context.emit(
            EventType.FILES_DISCOVERED, files=result.get("relevant_files", [])
        )
        return result

    async def risk_assessment(self, state: AgentState) -> dict[str, Any]:
        agent = RiskAgent(self.context)
        result = await agent.assess(state, self._tool_context(state, in_workspace=False))
        await self.context.emit(
            EventType.RISK_ASSESSED,
            risk=result.get("risk_level"),
            approval_required=result.get("approval_required"),
            reasons=result.get("risk_reasons", [])[:5],
        )
        if result.pop("_blocked", False):
            result["halt_reason"] = "policy blocked the change before any file was modified"
            result["policy_findings"] = result.get("risk_reasons", [])
        return result

    async def implementation(self, state: AgentState) -> dict[str, Any]:
        """Creates the isolated worktree, then lets the agent edit inside it."""
        workspace = self.context.workspaces.try_get(state["task_id"])
        if workspace is None:
            workspace = await self.context.workspaces.create(
                state["task_id"], Path(state["repository_path"])
            )
            await self.context.emit(
                EventType.WORKSPACE_CREATED,
                path=str(workspace.path),
                branch=workspace.branch,
            )

        agent = ImplementationAgent(self.context)
        result = await agent.implement(state, self._tool_context(state, in_workspace=True))
        result.update(await self._refresh_diff(state))
        result["workspace_path"] = str(workspace.path)
        result["git_branch"] = workspace.branch
        return result

    async def test_generation(self, state: AgentState) -> dict[str, Any]:
        agent = TestingAgent(self.context)
        result = await agent.generate(state, self._tool_context(state, in_workspace=True))
        result.update(await self._refresh_diff(state))
        return result

    async def run_tests(self, state: AgentState) -> dict[str, Any]:
        """Executed by the platform, not by an agent - the result must be trustworthy."""
        workspace_path = self._workspace_path(state)
        await self.context.emit(EventType.TESTS_STARTED, iteration=state.get("iteration", 0))

        kind = detect_project_kind(workspace_path)
        if kind != "dotnet":
            log.warning("tests.no_project", kind=kind)
            await self.context.emit(
                EventType.TESTS_PASSED, skipped=True, reason=f"no test project ({kind})"
            )
            return {
                "test_results": f"no runnable test project detected ({kind})",
                "test_failures": [],
                "tests_passed": 0,
                "tests_failed": 0,
                "test_run_ok": True,
            }

        command = await run_dotnet_test(
            workspace_path, self.context.settings.command_timeout_seconds
        )
        outcome = parse_dotnet_output(command)
        rendered = [failure.render() for failure in outcome.failures]
        signatures = signatures_for(rendered)
        history = list(state.get("failure_signature_history", []))
        history.append(signatures)

        update: dict[str, Any] = {
            "test_results": outcome.output[-12000:],
            "test_failures": rendered,
            "tests_passed": outcome.passed,
            "tests_failed": outcome.failed,
            "test_run_ok": outcome.ok,
            "failure_signatures": signatures,
            "failure_signature_history": history,
        }
        update.update(await self._refresh_diff(state))

        if outcome.ok:
            await self.context.emit(
                EventType.TESTS_PASSED, passed=outcome.passed, skipped=outcome.skipped
            )
        else:
            await self.context.emit(
                EventType.TEST_FAILED,
                failed=outcome.failed,
                iteration=state.get("iteration", 0),
                failures=rendered[:5],
            )
        return update

    async def debugging(self, state: AgentState) -> dict[str, Any]:
        iteration = state.get("iteration", 0) + 1
        await self.context.emit(
            EventType.DEBUG_ITERATION,
            iteration=iteration,
            failures=state.get("test_failures", [])[:3],
        )

        previous = list(state.get("previous_failures", []))
        for failure in state.get("test_failures", []):
            entry = f"iteration {iteration - 1}: {failure.splitlines()[0]}"
            if entry not in previous:
                previous.append(entry)

        working_state = dict(state)
        working_state["iteration"] = iteration
        agent = DebuggingAgent(self.context)
        result = await agent.debug(working_state, self._tool_context(state, in_workspace=True))

        analysis = result.get("debugging_analysis", "")
        if analysis:
            previous.append(f"iteration {iteration} analysis: {analysis.splitlines()[0][:200]}")

        update: dict[str, Any] = {
            "iteration": iteration,
            "debugging_analysis": analysis,
            "previous_failures": previous,
            "fix_applied": result.get("fix_applied", False),
            "confidence": result.get("confidence", "LOW"),
        }
        update.update(await self._refresh_diff(state))
        return update

    async def security_policy(self, state: AgentState) -> dict[str, Any]:
        """The deterministic gate that decides whether this change may be committed."""
        diff_update = await self._refresh_diff(state)
        files = diff_update.get("modified_files", state.get("modified_files", []))
        lines = diff_update.get("lines_added", 0) + diff_update.get("lines_removed", 0)

        decision = self.context.policy.evaluate(
            files=files, diff=diff_update.get("git_diff", ""), lines_changed=lines
        )
        risk = max_risk(RiskLevel(state.get("risk_level", "LOW")), decision.risk)
        await self.context.emit(
            EventType.POLICY_EVALUATED,
            action=decision.action.value,
            risk=risk.value,
            findings=decision.reasons()[:8],
        )

        update: dict[str, Any] = dict(diff_update)
        update.update(
            {
                "policy_action": decision.action.value,
                "policy_findings": decision.reasons(),
                "risk_level": risk.value,
                "approval_required": decision.action is not PolicyAction.ALLOW
                or risk is RiskLevel.HIGH
                or bool(files),
            }
        )
        if decision.blocked:
            await self.context.emit(EventType.POLICY_BLOCKED, findings=decision.reasons())
            update["halt_reason"] = f"policy blocked the change: {decision.summary()}"
        return update

    async def git_commit(self, state: AgentState) -> dict[str, Any]:
        workspace = self.context.workspaces.get(state["task_id"])
        if not state.get("modified_files"):
            return {
                "halt_reason": "the agent produced no file changes",
                "policy_action": PolicyAction.BLOCK.value,
            }
        try:
            sha = await commit_changes(state, workspace.path)
        except AgentPlatformError as exc:
            return {"halt_reason": f"commit failed: {exc}"}
        await self.context.emit(
            EventType.COMMIT_CREATED, sha=sha, branch=workspace.branch,
            files=state.get("modified_files", []),
        )
        return {"commit_sha": sha, "git_branch": workspace.branch}

    async def ci_validation(self, state: AgentState) -> dict[str, Any]:
        workspace = self.context.workspaces.get(state["task_id"])
        branch = state.get("git_branch", workspace.branch)
        provider = self.context.ci

        if provider.name != "none":
            await self.context.scm.push_branch(workspace.path, branch)

        await self.context.emit(EventType.CI_STARTED, branch=branch, provider=provider.name)
        run = await provider.trigger(branch, commit_sha=state.get("commit_sha"))
        if not run.finished and run.id:
            run = await provider.wait(run.id)
        logs = await provider.get_logs(run.id) if run.id else run.logs

        await self.context.record_ci_run(
            provider=provider.name,
            external_id=run.id or None,
            branch=branch,
            status=run.status.value,
            conclusion=run.status.value,
            url=run.url,
            logs=logs,
            iteration=state.get("ci_iteration", 0),
        )
        await self.context.emit(
            EventType.CI_COMPLETED, status=run.status.value, url=run.url, provider=provider.name
        )
        return {
            "ci_status": run.status.value,
            "ci_logs": logs or run.logs,
            "ci_run_id": run.id,
        }

    async def ci_debugging(self, state: AgentState) -> dict[str, Any]:
        iteration = state.get("ci_iteration", 0) + 1
        agent = CIAgent(self.context)
        working_state = dict(state)
        working_state["ci_iteration"] = iteration
        result = await agent.diagnose(
            working_state, self._tool_context(state, in_workspace=True)
        )
        update: dict[str, Any] = {
            "ci_iteration": iteration,
            "ci_analysis": result.get("ci_analysis", ""),
            "ci_requires_human": result.get("requires_human", False),
        }
        update.update(await self._refresh_diff(state))
        return update

    async def create_pr(self, state: AgentState) -> dict[str, Any]:
        workspace = self.context.workspaces.get(state["task_id"])
        pull_request = await open_pull_request(state, workspace.path, self.context.scm)
        await self.context.emit(
            EventType.PR_CREATED, url=pull_request.url, id=pull_request.id
        )
        return {"pull_request_url": pull_request.url}

    async def human_review(self, state: AgentState) -> dict[str, Any]:
        """Approval is a first-class state, not a notification (section 24)."""
        summary = _final_summary(state)
        reason = "; ".join(state.get("policy_findings", [])) or "routine agent change"
        await self.context.request_approval(reason)
        await self.context.emit(
            EventType.APPROVAL_REQUESTED,
            risk=state.get("risk_level"),
            files=state.get("modified_files", []),
            tests_passed=state.get("tests_passed", 0),
            ci=state.get("ci_status", ""),
        )
        return {
            "final_summary": summary,
            "approval_required": True,
            "outcome": "READY_FOR_REVIEW",
        }

    async def halt(self, state: AgentState) -> dict[str, Any]:
        reason = halt_reason(state)
        blocked = state.get("policy_action") == PolicyAction.BLOCK.value
        await self.context.emit(
            EventType.NO_PROGRESS_DETECTED if not blocked else EventType.POLICY_BLOCKED,
            reason=reason,
            iteration=state.get("iteration", 0),
        )
        return {
            "outcome": "HUMAN_REVIEW_REQUIRED",
            "halt_reason": reason,
            "final_summary": f"Stopped and escalated to a human. {reason}",
            "approval_required": True,
        }


def _final_summary(state: AgentState) -> str:
    parts = [
        state.get("implementation_summary") or state.get("plan_summary") or "Change prepared.",
        f"Files changed: {len(state.get('modified_files', []))}.",
        f"Tests: {state.get('tests_passed', 0)} passed, {state.get('tests_failed', 0)} failed.",
        f"CI: {state.get('ci_status') or 'not run'}.",
        f"Risk: {state.get('risk_level', 'LOW')}.",
        f"Debug iterations: {state.get('iteration', 0)}.",
    ]
    return " ".join(parts)
