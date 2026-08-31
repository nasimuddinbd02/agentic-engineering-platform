"""The AgentState contract (section 7).

State is the interface between workflow nodes.  Nodes return partial updates;
LangGraph merges them.  Everything here is JSON-serialisable because the whole
dictionary is checkpointed to PostgreSQL after every node, which is what lets a
second worker resume a task after the first one dies (section 55).
"""

from __future__ import annotations

from typing import Any, TypedDict

from core.domain import RiskLevel


class AgentState(TypedDict, total=False):
    task_id: str
    workflow_run_id: str

    repository_url: str
    repository_path: str
    workspace_path: str

    issue: str

    plan: list[str]
    plan_summary: str
    acceptance_criteria: list[str]

    relevant_files: list[str]
    repository_context: list[str]

    risk_level: str
    risk_reasons: list[str]
    approval_required: bool

    modified_files: list[str]
    git_diff: str
    lines_added: int
    lines_removed: int

    implementation_summary: str
    test_notes: list[str]
    test_files: list[str]
    test_plan_summary: str

    test_commands: list[str]
    test_results: str
    test_failures: list[str]
    tests_passed: int
    tests_failed: int
    #: True when the suite actually ran to completion (as opposed to not existing).
    test_run_ok: bool

    debugging_analysis: str
    previous_failures: list[str]
    failure_signatures: list[str]
    #: One entry per test run - two identical entries in a row means no progress.
    failure_signature_history: list[list[str]]
    fix_applied: bool
    confidence: str
    #: Scope guard: more changed files than this ends the loop (section 22).
    max_files: int

    iteration: int
    max_iterations: int
    ci_iteration: int
    max_ci_iterations: int

    ci_status: str
    ci_logs: str
    ci_run_id: str
    ci_analysis: str
    ci_requires_human: bool

    policy_action: str
    policy_findings: list[str]

    git_branch: str
    commit_sha: str
    pull_request_url: str

    #: Terminal routing decision made by the supervisor, not by a model.
    outcome: str
    halt_reason: str
    error: str

    final_summary: str


def initial_state(
    *,
    task_id: str,
    workflow_run_id: str,
    repository_url: str,
    repository_path: str,
    issue: str,
    max_iterations: int,
    max_ci_iterations: int,
) -> AgentState:
    return AgentState(
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        repository_url=repository_url,
        repository_path=repository_path,
        issue=issue,
        plan=[],
        acceptance_criteria=[],
        relevant_files=[],
        repository_context=[],
        risk_level=RiskLevel.LOW.value,
        risk_reasons=[],
        approval_required=False,
        modified_files=[],
        git_diff="",
        test_commands=[],
        test_results="",
        test_failures=[],
        previous_failures=[],
        failure_signatures=[],
        failure_signature_history=[],
        test_run_ok=False,
        max_files=12,
        iteration=0,
        max_iterations=max_iterations,
        ci_iteration=0,
        max_ci_iterations=max_ci_iterations,
        ci_status="",
        policy_action="",
        policy_findings=[],
        outcome="",
        halt_reason="",
    )


def summarize(state: AgentState) -> dict[str, Any]:
    """The compact result shape of section 45."""
    return {
        "task_id": state.get("task_id"),
        "summary": state.get("final_summary") or state.get("plan_summary", ""),
        "files_changed": state.get("modified_files", []),
        "tests": {
            "passed": state.get("tests_passed", 0),
            "failed": state.get("tests_failed", 0),
        },
        "ci": state.get("ci_status", ""),
        "risk": state.get("risk_level", RiskLevel.LOW.value),
        "iterations": state.get("iteration", 0),
        "branch": state.get("git_branch", ""),
        "pull_request_url": state.get("pull_request_url", ""),
        "approval_required": state.get("approval_required", False),
    }
