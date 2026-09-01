"""Deterministic routing (sections 9, 22, 23 and 51).

Every branch in the workflow is decided by these functions - never by a model.
The supervisor is the workflow controller, not the smartest agent.
"""

from __future__ import annotations

from core.domain import PolicyAction
from core.logging import get_logger
from graph.fingerprint import is_stuck
from graph.state import AgentState

log = get_logger(__name__)

HALT = "halt"


def after_risk(state: AgentState) -> str:
    """A BLOCK from the policy engine stops the task before any file is touched."""
    if state.get("policy_action") == PolicyAction.BLOCK.value:
        return HALT
    return "implementation"


def after_tests(state: AgentState) -> str:
    """PASS continues; FAIL debugs, but only while the budget and progress hold."""
    if (
        state.get("tests_failed", 0) == 0
        and state.get("tests_passed", 0) >= 0
        and state.get("test_run_ok", False)
    ):
        return "security_policy"

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)
    if iteration >= max_iterations:
        log.warning("routing.iteration_limit", iteration=iteration, limit=max_iterations)
        return HALT

    history = [
        signatures.split(",") if isinstance(signatures, str) else signatures
        for signatures in state.get("failure_signature_history", [])
    ]
    if is_stuck(history):
        log.warning("routing.no_progress", iteration=iteration)
        return HALT

    # A change that keeps growing is a change that is no longer understood.
    if len(state.get("modified_files", [])) > state.get("max_files", 12):
        log.warning("routing.scope_expanded", files=len(state.get("modified_files", [])))
        return HALT

    return "debugging"


def after_policy(state: AgentState) -> str:
    if state.get("policy_action") == PolicyAction.BLOCK.value:
        return HALT
    return "git_commit"


def after_commit(state: AgentState) -> str:
    """No commit means there is nothing to validate, push or review.

    Without this gate a task that changed nothing would still walk through CI,
    open a pull request, and ask a human to review an empty diff.
    """
    if not state.get("commit_sha"):
        log.warning("routing.no_commit", reason=state.get("halt_reason"))
        return HALT
    return "ci_validation"


def after_ci(state: AgentState) -> str:
    status = (state.get("ci_status") or "").upper()
    if status in ("PASSED", "SKIPPED", ""):
        return "create_pr"
    if state.get("ci_requires_human", False):
        return HALT
    if state.get("ci_iteration", 0) >= state.get("max_ci_iterations", 2):
        log.warning("routing.ci_limit", iteration=state.get("ci_iteration"))
        return HALT
    return "ci_debugging"


def halt_reason(state: AgentState) -> str:
    """Human-readable explanation attached to the terminal state."""
    if state.get("halt_reason"):
        return str(state["halt_reason"])
    if state.get("policy_action") == PolicyAction.BLOCK.value:
        return "policy blocked the change: " + "; ".join(state.get("policy_findings", []))
    if state.get("tests_failed", 0):
        return (
            f"tests still failing after {state.get('iteration', 0)} debugging "
            f"iteration(s) - handing over to a human"
        )
    if (state.get("ci_status") or "").upper() == "FAILED":
        return f"CI still failing after {state.get('ci_iteration', 0)} attempt(s)"
    return "workflow halted"
