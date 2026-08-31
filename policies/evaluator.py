"""Policy engine (section 25).

Deterministic, testable, and independent of the model: given a set of changed
files and a diff, it returns an action (ALLOW / HUMAN_APPROVAL / BLOCK), a risk
level, and the reasons.  ``Prompt = guidance, Policy = authorization, Code =
enforcement`` (section 49).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from core.domain import PolicyAction, RiskLevel, max_risk

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.yaml")

_ACTION_STRENGTH = {
    PolicyAction.ALLOW: 0,
    PolicyAction.HUMAN_APPROVAL: 1,
    PolicyAction.BLOCK: 2,
}


@dataclass(frozen=True)
class Rule:
    name: str
    action: PolicyAction
    risk: RiskLevel
    description: str = ""
    patterns: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    content: tuple[str, ...] = ()

    def matches_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        basename = normalized.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(basename, pattern) for pattern in self.patterns):
            return True
        return any(fragment.lower() in normalized.lower() for fragment in self.paths)

    def matches_content(self, added_lines: str) -> bool:
        return any(re.search(expression, added_lines) for expression in self.content)


@dataclass
class PolicyFinding:
    rule: str
    action: PolicyAction
    risk: RiskLevel
    reason: str


@dataclass
class PolicyDecision:
    action: PolicyAction
    risk: RiskLevel
    findings: list[PolicyFinding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action is PolicyAction.BLOCK

    @property
    def requires_approval(self) -> bool:
        return self.action in (PolicyAction.HUMAN_APPROVAL, PolicyAction.BLOCK)

    def reasons(self) -> list[str]:
        return [f"{finding.rule}: {finding.reason}" for finding in self.findings]

    def summary(self) -> str:
        if not self.findings:
            return "no policy findings"
        return "; ".join(self.reasons())


def _resolve(findings: list[PolicyFinding]) -> PolicyDecision:
    """The strongest action wins; risk is the highest any finding reports."""
    action = PolicyAction.ALLOW
    for finding in findings:
        if _ACTION_STRENGTH[finding.action] > _ACTION_STRENGTH[action]:
            action = finding.action
    return PolicyDecision(
        action=action, risk=max_risk(*(finding.risk for finding in findings)), findings=findings
    )


def added_lines_of(diff: str) -> str:
    return "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


class PolicyEngine:
    def __init__(self, rules: list[Rule], thresholds: dict[str, int]) -> None:
        self.rules = rules
        self.thresholds = thresholds

    @classmethod
    def from_file(cls, path: Path | None = None) -> PolicyEngine:
        document = yaml.safe_load((path or DEFAULT_RULES_PATH).read_text(encoding="utf-8"))
        rules = [
            Rule(
                name=entry["name"],
                action=PolicyAction(entry.get("action", "ALLOW")),
                risk=RiskLevel(entry.get("risk", "LOW")),
                description=entry.get("description", ""),
                patterns=tuple(entry.get("patterns", ())),
                paths=tuple(entry.get("paths", ())),
                content=tuple(entry.get("content", ())),
            )
            for entry in document.get("rules", [])
        ]
        return cls(rules, dict(document.get("thresholds", {})))

    def evaluate(
        self,
        *,
        files: list[str],
        diff: str = "",
        lines_changed: int | None = None,
        apply_scope_thresholds: bool = True,
    ) -> PolicyDecision:
        """Evaluate a set of files against the rules.

        ``apply_scope_thresholds`` is False before any file has been modified -
        during risk assessment ``files`` is the list of *candidate* files to
        read, and counting those as change scope would over-report risk on every
        task that needs to look at more than a few files.
        """
        findings: list[PolicyFinding] = []
        added = added_lines_of(diff) if diff else ""

        for rule in self.rules:
            hit_paths = [path for path in files if rule.matches_path(path)]
            if hit_paths:
                findings.append(
                    PolicyFinding(
                        rule=rule.name,
                        action=rule.action,
                        risk=rule.risk,
                        reason=f"{rule.description or 'matched'} ({', '.join(hit_paths[:5])})",
                    )
                )
            elif rule.content and added and rule.matches_content(added):
                findings.append(
                    PolicyFinding(
                        rule=rule.name,
                        action=rule.action,
                        risk=rule.risk,
                        reason=rule.description or "matched added content",
                    )
                )

        if not apply_scope_thresholds:
            return _resolve(findings)

        max_files = self.thresholds.get("max_files_changed", 12)
        if len(files) > max_files:
            findings.append(
                PolicyFinding(
                    rule="scope-sprawl",
                    action=PolicyAction.HUMAN_APPROVAL,
                    risk=RiskLevel.HIGH,
                    reason=f"{len(files)} files changed (limit {max_files})",
                )
            )

        max_lines = self.thresholds.get("max_lines_changed", 800)
        if lines_changed is not None and lines_changed > max_lines:
            findings.append(
                PolicyFinding(
                    rule="large-change",
                    action=PolicyAction.HUMAN_APPROVAL,
                    risk=RiskLevel.MEDIUM,
                    reason=f"{lines_changed} lines changed (limit {max_lines})",
                )
            )

        medium_files = self.thresholds.get("medium_risk_files", 4)
        if len(files) >= medium_files:
            findings.append(
                PolicyFinding(
                    rule="multi-file-change",
                    action=PolicyAction.ALLOW,
                    risk=RiskLevel.MEDIUM,
                    reason=f"{len(files)} files changed",
                )
            )

        return _resolve(findings)

    def check_path_writable(self, path: str) -> PolicyDecision:
        """Pre-write gate, so a blocked file is never modified in the first place."""
        return self.evaluate(files=[path], apply_scope_thresholds=False)


@lru_cache
def get_policy_engine() -> PolicyEngine:
    return PolicyEngine.from_file()


def reload_policy_engine() -> PolicyEngine:
    get_policy_engine.cache_clear()
    return get_policy_engine()


def rules_as_dicts() -> list[dict[str, Any]]:
    engine = get_policy_engine()
    return [
        {
            "name": rule.name,
            "action": rule.action.value,
            "risk": rule.risk.value,
            "description": rule.description,
        }
        for rule in engine.rules
    ]
