"""Local provider - the default for the POC.

The branch stays in the developer's own repository and the "pull request" is a
review record written to the artifact directory.  It exercises the whole
workflow with no network, no token, and no possibility of pushing anywhere real.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.ids import new_id
from core.logging import get_logger
from core.time import utcnow
from providers.scm.base import PullRequest, SourceControlProvider
from tools.runner import run_command

log = get_logger(__name__)


class LocalGitProvider(SourceControlProvider):
    name = "local"

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    async def push_branch(self, workspace_path: Path, branch: str) -> str:
        """No remote: the worktree commit already lives in the parent repository."""
        result = await run_command(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace_path, timeout=60
        )
        log.info("scm.local.branch_ready", branch=result.stdout.strip() or branch)
        return f"local:{branch}"

    async def create_pull_request(
        self, *, branch: str, title: str, body: str, base: str = "main"
    ) -> PullRequest:
        identifier = new_id("pr")
        record = {
            "id": identifier,
            "title": title,
            "body": body,
            "branch": branch,
            "base": base,
            "state": "OPEN",
            "created_at": utcnow().isoformat(),
        }
        path = self.artifact_root / f"{identifier}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        return PullRequest(
            id=identifier, url=path.as_uri(), title=title, branch=branch, state="OPEN"
        )

    async def get_pull_request(self, identifier: str) -> PullRequest | None:
        path = self.artifact_root / f"{identifier}.json"
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        return PullRequest(
            id=record["id"],
            url=path.as_uri(),
            title=record["title"],
            branch=record["branch"],
            state=record.get("state", "OPEN"),
        )
