"""GitHub Actions provider (section 28).

Triggering is push-driven: the workflow file reacts to the agent branch, so
``trigger`` finds the run GitHub started for our commit rather than dispatching
a second one.  Falls back to workflow_dispatch when the workflow declares it.
"""

from __future__ import annotations

import asyncio

import httpx

from core.errors import ConfigurationError, TransientInfrastructureError
from core.logging import get_logger
from providers.ci.base import CIPipelineProvider, CIRunResult, CIStatus

log = get_logger(__name__)

API_ROOT = "https://api.github.com"

_CONCLUSION_MAP = {
    "success": CIStatus.PASSED,
    "failure": CIStatus.FAILED,
    "timed_out": CIStatus.TIMED_OUT,
    "cancelled": CIStatus.FAILED,
    "startup_failure": CIStatus.FAILED,
    "skipped": CIStatus.SKIPPED,
    "neutral": CIStatus.PASSED,
}


class GitHubActionsProvider(CIPipelineProvider):
    name = "github_actions"

    def __init__(self, token: str, repository: str, *, timeout: int = 60) -> None:
        if not token or "/" not in repository:
            raise ConfigurationError(
                "GITHUB_TOKEN and GITHUB_REPOSITORY are required for CI_PROVIDER=github_actions"
            )
        self.repository = repository
        self.client = httpx.AsyncClient(
            base_url=API_ROOT,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def trigger(self, branch: str, *, commit_sha: str | None = None) -> CIRunResult:
        # The push already started a run; give GitHub a moment to register it.
        for attempt in range(6):
            runs = await self._list_runs(branch)
            for run in runs:
                if commit_sha is None or run.get("head_sha") == commit_sha:
                    return self._to_result(run)
            await asyncio.sleep(2 * (attempt + 1))
        log.warning("ci.github.no_run_found", branch=branch)
        return CIRunResult(
            id="",
            status=CIStatus.SKIPPED,
            logs=f"no workflow run found for {branch}",
        )

    async def _list_runs(self, branch: str) -> list[dict]:
        response = await self.client.get(
            f"/repos/{self.repository}/actions/runs",
            params={"branch": branch, "per_page": 10},
        )
        if response.status_code >= 500:
            raise TransientInfrastructureError(f"github actions {response.status_code}")
        response.raise_for_status()
        return response.json().get("workflow_runs", [])

    def _to_result(self, run: dict) -> CIRunResult:
        status = run.get("status")
        if status in ("queued", "waiting", "requested", "pending"):
            resolved = CIStatus.PENDING
        elif status == "in_progress":
            resolved = CIStatus.RUNNING
        else:
            resolved = _CONCLUSION_MAP.get(run.get("conclusion") or "", CIStatus.FAILED)
        return CIRunResult(id=str(run["id"]), status=resolved, url=run.get("html_url", ""))

    async def get_status(self, run_id: str) -> CIRunResult:
        if not run_id:
            return CIRunResult(id="", status=CIStatus.SKIPPED)
        response = await self.client.get(f"/repos/{self.repository}/actions/runs/{run_id}")
        if response.status_code == 404:
            return CIRunResult(id=run_id, status=CIStatus.SKIPPED)
        response.raise_for_status()
        return self._to_result(response.json())

    async def get_logs(self, run_id: str) -> str:
        """Job-level annotations - enough for the CI debugging agent to act on."""
        if not run_id:
            return ""
        response = await self.client.get(f"/repos/{self.repository}/actions/runs/{run_id}/jobs")
        if response.status_code != 200:
            return ""
        lines: list[str] = []
        for job in response.json().get("jobs", []):
            lines.append(f"job {job['name']}: {job.get('conclusion')}")
            for step in job.get("steps", []):
                if step.get("conclusion") in ("failure", "cancelled"):
                    lines.append(f"  FAILED step: {step['name']}")
        return "\n".join(lines)

    async def close(self) -> None:
        await self.client.aclose()
