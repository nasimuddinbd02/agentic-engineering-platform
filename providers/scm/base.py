"""Source control provider abstraction (section 27).

Nothing above this interface knows whether the platform is talking to GitHub,
Azure DevOps, or a bare repository on disk.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PullRequest:
    id: str
    url: str
    title: str
    branch: str
    state: str = "OPEN"


class SourceControlProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def push_branch(self, workspace_path: Path, branch: str) -> str:
        """Publish the branch. Returns a human-readable location."""

    @abstractmethod
    async def create_pull_request(
        self, *, branch: str, title: str, body: str, base: str = "main"
    ) -> PullRequest: ...

    @abstractmethod
    async def get_pull_request(self, identifier: str) -> PullRequest | None: ...

    async def close(self) -> None:  # pragma: no cover - adapters override
        return None
