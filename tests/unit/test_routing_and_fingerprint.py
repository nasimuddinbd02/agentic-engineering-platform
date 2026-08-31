"""Routing and failure fingerprinting (sections 22, 23 and 9).

These decide when the agent stops.  They are pure functions on purpose - the
stopping rules must be readable and testable without a model or a database.
"""

from __future__ import annotations

from graph.fingerprint import failure_signature, is_stuck, normalize, signatures_for
from graph.routing import HALT, after_ci, after_policy, after_risk, after_tests
from graph.state import AgentState


def state(**overrides) -> AgentState:
    base: AgentState = {
        "iteration": 0,
        "max_iterations": 3,
        "ci_iteration": 0,
        "max_ci_iterations": 2,
        "tests_passed": 0,
        "tests_failed": 0,
        "test_run_ok": True,
        "modified_files": [],
        "max_files": 12,
        "failure_signature_history": [],
        "policy_action": "ALLOW",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------ fingerprint


def test_signature_ignores_line_numbers_and_guids() -> None:
    first = failure_signature(
        "OrderTests.Cancel",
        "PaymentGatewayException",
        "Order 3f2504e0-4f89-11d3-9a0c-0305e82c3301 already refunded at line 42",
    )
    second = failure_signature(
        "OrderTests.Cancel",
        "PaymentGatewayException",
        "Order 7c9e6679-7425-40de-944b-e07fc1f90ae7 already refunded at line 58",
    )
    assert first == second


def test_signature_distinguishes_different_failures() -> None:
    first = failure_signature("A.Test", "NullReferenceException", "object was null")
    second = failure_signature("A.Test", "InvalidOperationException", "wrong state")
    assert first != second


def test_signature_distinguishes_different_tests() -> None:
    assert failure_signature("A.One", "X", "m") != failure_signature("A.Two", "X", "m")


def test_normalize_collapses_paths_and_timestamps() -> None:
    text = normalize(r"failed at C:\repo\src\A.cs on 2026-08-31T10:00:00Z after 12ms")
    assert "<path>" in text
    assert "<timestamp>" in text
    assert "<duration>" in text
    assert "repo" not in text
    assert "2026" not in text


def test_signatures_for_parses_rendered_failures() -> None:
    rendered = ["OrderTests.Cancel: PaymentGatewayException\n  already refunded"]
    assert len(signatures_for(rendered)) == 1


def test_is_stuck_requires_two_identical_rounds() -> None:
    assert not is_stuck([])
    assert not is_stuck([["a"]])
    assert not is_stuck([["a"], ["b"]])
    assert is_stuck([["a"], ["a"]])
    assert not is_stuck([["a"], ["a"], ["b"]])
    assert not is_stuck([[], []]), "an empty failure set is not evidence of being stuck"


# --------------------------------------------------------------------- routing


def test_passing_tests_continue_to_policy() -> None:
    assert after_tests(state(tests_passed=9, test_run_ok=True)) == "security_policy"


def test_failing_tests_route_to_debugging() -> None:
    assert after_tests(state(tests_failed=1, test_run_ok=False)) == "debugging"


def test_iteration_limit_halts() -> None:
    assert after_tests(state(tests_failed=1, test_run_ok=False, iteration=3)) == HALT


def test_repeated_failure_halts_before_the_limit() -> None:
    stuck = state(
        tests_failed=1,
        test_run_ok=False,
        iteration=1,
        failure_signature_history=[["sig-a"], ["sig-a"]],
    )
    assert after_tests(stuck) == HALT


def test_scope_expansion_halts() -> None:
    sprawling = state(
        tests_failed=1,
        test_run_ok=False,
        iteration=1,
        modified_files=[f"f{index}.cs" for index in range(20)],
    )
    assert after_tests(sprawling) == HALT


def test_blocked_policy_halts_before_implementation() -> None:
    assert after_risk(state(policy_action="BLOCK")) == HALT
    assert after_risk(state(policy_action="HUMAN_APPROVAL")) == "implementation"


def test_blocked_policy_prevents_commit() -> None:
    assert after_policy(state(policy_action="BLOCK")) == HALT
    assert after_policy(state(policy_action="HUMAN_APPROVAL")) == "git_commit"


def test_ci_outcomes() -> None:
    assert after_ci(state(ci_status="PASSED")) == "create_pr"
    assert after_ci(state(ci_status="SKIPPED")) == "create_pr"
    assert after_ci(state(ci_status="FAILED")) == "ci_debugging"
    assert after_ci(state(ci_status="FAILED", ci_iteration=2)) == HALT
    assert after_ci(state(ci_status="FAILED", ci_requires_human=True)) == HALT


def test_no_commit_halts_before_ci_and_review() -> None:
    """A task that changed nothing must not reach a reviewer."""
    from graph.routing import after_commit

    assert after_commit(state(commit_sha="")) == HALT
    assert after_commit(state()) == HALT
    assert after_commit(state(commit_sha="abc123")) == "ci_validation"
