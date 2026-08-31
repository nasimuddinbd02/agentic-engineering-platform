"""No-CI provider.

Default for the POC: the workflow still walks through the CI node and records a
ci_runs row, but reports SKIPPED instead of pretending a pipeline passed.
Section 26 is only meaningful once a real pipeline exists.
"""

from __future__ import annotations

from core.ids import new_id
from providers.ci.base import CIPipelineProvider, CIRunResult, CIStatus


class NoopCIProvider(CIPipelineProvider):
    name = "none"

    def __init__(self) -> None:
        self._runs: dict[str, CIRunResult] = {}

    async def trigger(self, branch: str, *, commit_sha: str | None = None) -> CIRunResult:
        identifier = new_id("cirun")
        result = CIRunResult(
            id=identifier,
            status=CIStatus.SKIPPED,
            logs=f"CI_PROVIDER=none - no pipeline configured for branch {branch}",
        )
        self._runs[identifier] = result
        return result

    async def get_status(self, run_id: str) -> CIRunResult:
        return self._runs.get(run_id, CIRunResult(id=run_id, status=CIStatus.SKIPPED))

    async def get_logs(self, run_id: str) -> str:
        return self._runs.get(run_id, CIRunResult(id=run_id, status=CIStatus.SKIPPED)).logs
