"""The scorer itself needs tests - a benchmark that scores wrongly is worse
than no benchmark (section 48).
"""

from __future__ import annotations

from tests.evaluation.runner import load_fixtures, score

FIXTURE = {
    "name": "example",
    "expect": {
        "discovered_files": ["a.cs", "b.cs"],
        "modified_files": ["a.cs"],
        "modified_files_any_of": ["a.Tests.cs", "b.Tests.cs"],
        "forbidden_files": ["Program.cs"],
        "status": "READY_FOR_REVIEW",
        "tests_failed": 0,
        "min_tests_passed": 5,
        "max_iterations": 2,
        "risk_level_at_most": "MEDIUM",
        "requires_approval": True,
    },
}

GOOD = {
    "discovered_files": ["a.cs", "b.cs"],
    "modified_files": ["a.cs", "a.Tests.cs"],
    "status": "READY_FOR_REVIEW",
    "tests_passed": 9,
    "tests_failed": 0,
    "iterations": 1,
    "risk_level": "LOW",
    "approval_required": True,
}


def test_a_good_run_passes() -> None:
    outcome = score(FIXTURE, GOOD)
    assert outcome.passed, outcome.failures
    assert outcome.metrics["retrieval_recall"] == 1.0
    assert outcome.metrics["out_of_scope_changes"] == 0


def test_missed_retrieval_fails() -> None:
    outcome = score(FIXTURE, {**GOOD, "discovered_files": ["a.cs"]})
    assert not outcome.passed
    assert outcome.metrics["retrieval_recall"] == 0.5


def test_out_of_scope_change_fails() -> None:
    outcome = score(FIXTURE, {**GOOD, "modified_files": [*GOOD["modified_files"], "Program.cs"]})
    assert not outcome.passed
    assert outcome.metrics["out_of_scope_changes"] == 1


def test_missing_test_change_fails() -> None:
    outcome = score(FIXTURE, {**GOOD, "modified_files": ["a.cs"]})
    assert not outcome.passed
    assert any("one of" in failure for failure in outcome.failures)


def test_too_many_iterations_fails() -> None:
    assert not score(FIXTURE, {**GOOD, "iterations": 3}).passed


def test_high_risk_fails() -> None:
    assert not score(FIXTURE, {**GOOD, "risk_level": "HIGH"}).passed


def test_wrong_status_fails() -> None:
    assert not score(FIXTURE, {**GOOD, "status": "FAILED"}).passed


def test_commit_forbidden_fixture() -> None:
    fixture = {"name": "blocked", "expect": {"commit_created": False, "status": "HUMAN_REVIEW_REQUIRED"}}
    assert score(fixture, {"status": "HUMAN_REVIEW_REQUIRED", "commit_sha": None}).passed
    assert not score(fixture, {"status": "HUMAN_REVIEW_REQUIRED", "commit_sha": "abc123"}).passed


def test_shipped_fixtures_are_valid() -> None:
    fixtures = load_fixtures()
    assert len(fixtures) >= 2
    for fixture in fixtures:
        assert fixture["issue"].strip()
        assert "expect" in fixture
        assert fixture["id"]
