"""Policy engine tests (section 25).

Authorization must be deterministic, so these are the tests that matter most:
they encode what the platform will and will not let an agent do.
"""

from __future__ import annotations

import pytest

from core.domain import PolicyAction, RiskLevel
from policies.evaluator import PolicyEngine, added_lines_of


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine.from_file()


def test_ordinary_change_is_allowed(engine: PolicyEngine) -> None:
    decision = engine.evaluate(
        files=["src/OrderService/Services/OrderService.cs"], lines_changed=12
    )
    assert decision.action is PolicyAction.ALLOW
    assert decision.risk is RiskLevel.LOW
    assert not decision.blocked


@pytest.mark.parametrize(
    "path",
    [
        "src/.env",
        "config/production.pem",
        "src/aws-credentials.json",
        "app/secrets.yaml",
    ],
)
def test_secret_files_are_blocked(engine: PolicyEngine, path: str) -> None:
    decision = engine.evaluate(files=[path])
    assert decision.blocked
    assert decision.risk is RiskLevel.HIGH


def test_secret_value_in_diff_is_blocked(engine: PolicyEngine) -> None:
    diff = (
        "--- a/src/Config.cs\n+++ b/src/Config.cs\n"
        '+    private const string Password = "sup3rsecret";\n'
    )
    decision = engine.evaluate(files=["src/Config.cs"], diff=diff)
    assert decision.blocked


def test_private_key_in_diff_is_blocked(engine: PolicyEngine) -> None:
    diff = "+++ b/x\n+-----BEGIN RSA PRIVATE KEY-----\n"
    assert engine.evaluate(files=["x"], diff=diff).blocked


def test_auth_paths_require_human_approval(engine: PolicyEngine) -> None:
    decision = engine.evaluate(files=["src/Authentication/TokenValidator.cs"])
    assert decision.action is PolicyAction.HUMAN_APPROVAL
    assert not decision.blocked
    assert decision.requires_approval


def test_production_infrastructure_is_blocked(engine: PolicyEngine) -> None:
    assert engine.evaluate(files=["infra/prod/main.tf"]).blocked


def test_project_file_change_requires_approval(engine: PolicyEngine) -> None:
    decision = engine.evaluate(files=["src/OrderService/OrderService.csproj"])
    assert decision.action is PolicyAction.HUMAN_APPROVAL


def test_scope_sprawl_requires_approval(engine: PolicyEngine) -> None:
    decision = engine.evaluate(files=[f"src/File{index}.cs" for index in range(20)])
    assert decision.action is PolicyAction.HUMAN_APPROVAL
    assert "scope-sprawl" in decision.summary()


def test_scope_thresholds_are_skipped_before_any_change(engine: PolicyEngine) -> None:
    """Risk assessment evaluates candidate files, which are not change scope."""
    candidates = [f"src/File{index}.cs" for index in range(20)]
    decision = engine.evaluate(files=candidates, apply_scope_thresholds=False)
    assert decision.action is PolicyAction.ALLOW
    assert decision.risk is RiskLevel.LOW


def test_large_change_requires_approval(engine: PolicyEngine) -> None:
    decision = engine.evaluate(files=["src/A.cs"], lines_changed=5000)
    assert decision.action is PolicyAction.HUMAN_APPROVAL


def test_strongest_action_wins(engine: PolicyEngine) -> None:
    decision = engine.evaluate(files=["src/Authentication/A.cs", "src/.env"])
    assert decision.action is PolicyAction.BLOCK


def test_check_path_writable_gates_a_single_write(engine: PolicyEngine) -> None:
    assert engine.check_path_writable("src/.env").blocked
    assert not engine.check_path_writable("src/Services/OrderService.cs").blocked


def test_added_lines_ignores_removals_and_headers() -> None:
    diff = "--- a/x\n+++ b/x\n+added line\n-removed line\n context\n"
    assert added_lines_of(diff) == "added line"
