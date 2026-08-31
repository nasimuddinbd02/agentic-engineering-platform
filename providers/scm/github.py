"""GitHub provider (section 27).

Pushes the agent branch and opens a pull request through the REST API.  The
token is read from configuration and never written into the workspace, the
diff, or a log line.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from core.errors import ConfigurationError, TransientInfrastructureError
from core.logging import get_logger
from providers.scm.base import PullRequest, SourceControlProvider
from tools.runner import run_command

log = get_logger(__name__)

API_ROOT = "https://api.github.com"


class GitHubProvider(SourceControlProvider):
    name = "github"

    def __init__(self, token: str, repository: str, *, timeout: int = 60) -> None:
        if not token:
            raise ConfigurationError("GITHUB_TOKEN is required for SCM_PROVIDER=github")
        if "/" not in repository:
            raise ConfigurationError("GITHUB_REPOSITORY must be 'owner/name'")
        self.token = token
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

    async def push_branch(self, workspace_path: Path, branch: str) -> str:
        remote = f"https://x-access-token:{self.token}@github.com/{self.repository}.git"
        result = await run_command(
            ["git", "push", remote, f"HEAD:refs/heads/{branch}"],
            cwd=workspace_path,
            timeout=300,
        )
        if result.exit_code != 0:
            # Never echo the command: it carries the token.
            raise TransientInfrastructureError(
                f"git push failed with exit code {result.exit_code}"
            )
        log.info("scm.github.pushed", branch=branch, repository=self.repository)
        return f"https://github.com/{self.repository}/tree/{branch}"

    async def create_pull_request(
        self, *, branch: str, title: str, body: str, base: str = "main"
    ) -> PullRequest:
        response = await self.client.post(
            f"/repos/{self.repository}/pulls",
            json={"title": title, "body": body, "head": branch, "base": base},
        )
        if response.status_code >= 500:
            raise TransientInfrastructureError(f"github {response.status_code}")
        response.raise_for_status()
        payload = response.json()
        return PullRequest(
            id=str(payload["number"]),
            url=payload["html_url"],
            title=payload["title"],
            branch=branch,
            state=payload.get("state", "open").upper(),
        )

    async def get_pull_request(self, identifier: str) -> PullRequest | None:
        response = await self.client.get(f"/repos/{self.repository}/pulls/{identifier}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return PullRequest(
            id=str(payload["number"]),
            url=payload["html_url"],
            title=payload["title"],
            branch=payload["head"]["ref"],
            state=payload.get("state", "open").upper(),
        )

    async def close(self) -> None:
        await self.client.aclose()
