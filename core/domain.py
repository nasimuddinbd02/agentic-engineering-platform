"""Domain vocabulary shared by every layer: task states, events, risk levels.

The state machine of section 30 is enforced here rather than in prompts.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    QUEUED = "QUEUED"
    PLANNING = "PLANNING"
    REPOSITORY_ANALYSIS = "REPOSITORY_ANALYSIS"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    TEST_FAILED = "TEST_FAILED"
    DEBUGGING = "DEBUGGING"
    TEST_PASSED = "TEST_PASSED"
    CI_RUNNING = "CI_RUNNING"
    CI_FAILED = "CI_FAILED"
    CI_DEBUGGING = "CI_DEBUGGING"
    CI_PASSED = "CI_PASSED"
    POLICY_CHECK = "POLICY_CHECK"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    PR_CREATED = "PR_CREATED"
    # terminal
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.REJECTED,
        TaskStatus.HUMAN_REVIEW_REQUIRED,
    }
)

#: States in which a task is parked waiting for a person, not for a worker.
WAITING_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.READY_FOR_REVIEW, TaskStatus.HUMAN_REVIEW_REQUIRED}
)


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


def max_risk(*levels: RiskLevel | str | None) -> RiskLevel:
    best = RiskLevel.LOW
    for level in levels:
        if level is None:
            continue
        candidate = RiskLevel(level)
        if RISK_ORDER[candidate] > RISK_ORDER[best]:
            best = candidate
    return best


class PolicyAction(StrEnum):
    ALLOW = "ALLOW"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    BLOCK = "BLOCK"


class EventType(StrEnum):
    TASK_CREATED = "TASK_CREATED"
    TASK_CLAIMED = "TASK_CLAIMED"
    NODE_STARTED = "NODE_STARTED"
    NODE_COMPLETED = "NODE_COMPLETED"
    TOOL_CALLED = "TOOL_CALLED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    PLAN_CREATED = "PLAN_CREATED"
    FILES_DISCOVERED = "FILES_DISCOVERED"
    RISK_ASSESSED = "RISK_ASSESSED"
    WORKSPACE_CREATED = "WORKSPACE_CREATED"
    FILE_CHANGED = "FILE_CHANGED"
    TESTS_STARTED = "TESTS_STARTED"
    TESTS_PASSED = "TESTS_PASSED"
    TEST_FAILED = "TEST_FAILED"
    DEBUG_ITERATION = "DEBUG_ITERATION"
    NO_PROGRESS_DETECTED = "NO_PROGRESS_DETECTED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    COMMIT_CREATED = "COMMIT_CREATED"
    CI_STARTED = "CI_STARTED"
    CI_COMPLETED = "CI_COMPLETED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    PR_CREATED = "PR_CREATED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"


#: Node name -> status the task moves into while that node runs (section 30).
NODE_STATUS: dict[str, TaskStatus] = {
    "plan": TaskStatus.PLANNING,
    "repository_analysis": TaskStatus.REPOSITORY_ANALYSIS,
    "risk_assessment": TaskStatus.RISK_ASSESSMENT,
    "implementation": TaskStatus.IMPLEMENTING,
    "test_generation": TaskStatus.TESTING,
    "run_tests": TaskStatus.TESTING,
    "debugging": TaskStatus.DEBUGGING,
    "ci_validation": TaskStatus.CI_RUNNING,
    "ci_debugging": TaskStatus.CI_DEBUGGING,
    "security_policy": TaskStatus.POLICY_CHECK,
    "git_commit": TaskStatus.TEST_PASSED,
    "create_pr": TaskStatus.PR_CREATED,
    "human_review": TaskStatus.READY_FOR_REVIEW,
}
