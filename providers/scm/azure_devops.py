"""Azure DevOps provider (section 27).

Present so the abstraction is demonstrably provider-neutral: the same workflow
node drives GitHub or Azure DevOps with no change above this file.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from core.errors import ConfigurationError, TransientInfrastructureError
from providers.scm.base import PullRequest, SourceControlProvider
from tools.runner import run_command

API_VERSION = "7.1"


class AzureDevOpsProvider(SourceControlProvider):
    name = "azure_devops"

    def __init__(
        self, *, organization: str, project: str, repository: str, token: str, timeout: int = 60
    ) -> None:
        if not token:
            raise ConfigurationError("a PAT is required for SCM_PROVIDER=azure_devops")
        self.organization = organization
        self.project = project
        self.repository = repository
        self.token = token
        credential = base64.b64encode(f":{token}".encode()).decode()
        self.client = httpx.AsyncClient(
            base_url=f"https://dev.azure.com/{organization}/{project}/_apis",
            timeout=timeout,
            headers={"Authorization": f"Basic {credential}"},
        )

    async def push_branch(self, workspace_path: Path, branch: str) -> str:
        remote = (
            f"https://{self.token}@dev.azure.com/{self.organization}/{self.project}"
            f"/_git/{self.repository}"
        )
        result = await run_command(
            ["git", "push", remote, f"HEAD:refs/heads/{branch}"],
            cwd=workspace_path,
            timeout=300,
        )
        if result.exit_code != 0:
            raise TransientInfrastructureError(f"git push failed ({result.exit_code})")
        return f"azure:{self.repository}/{branch}"

    async def create_pull_request(
        self, *, branch: str, title: str, body: str, base: str = "main"
    ) -> PullRequest:
        response = await self.client.post(
            f"/git/repositories/{self.repository}/pullrequests",
            params={"api-version": API_VERSION},
            json={
                "sourceRefName": f"refs/heads/{branch}",
                "targetRefName": f"refs/heads/{base}",
                "title": title,
                "description": body,
            },
        )
        if response.status_code >= 500:
            raise TransientInfrastructureError(f"azure devops {response.status_code}")
        response.raise_for_status()
        payload = response.json()
        identifier = str(payload["pullRequestId"])
        return PullRequest(
            id=identifier,
            url=(
                f"https://dev.azure.com/{self.organization}/{self.project}"
                f"/_git/{self.repository}/pullrequest/{identifier}"
            ),
            title=title,
            branch=branch,
            state=payload.get("status", "active").upper(),
        )

    async def get_pull_request(self, identifier: str) -> PullRequest | None:
        response = await self.client.get(
            f"/git/repositories/{self.repository}/pullrequests/{identifier}",
            params={"api-version": API_VERSION},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        return PullRequest(
            id=identifier,
            url=payload.get("url", ""),
            title=payload.get("title", ""),
            branch=payload.get("sourceRefName", "").replace("refs/heads/", ""),
            state=payload.get("status", "active").upper(),
        )

    async def close(self) -> None:
        await self.client.aclose()
