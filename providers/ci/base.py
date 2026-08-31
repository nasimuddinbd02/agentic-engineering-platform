"""CI pipeline provider abstraction (section 28)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class CIStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class CIRunResult:
    id: str
    status: CIStatus
    url: str = ""
    logs: str = ""

    @property
    def finished(self) -> bool:
        return self.status in (
            CIStatus.PASSED,
            CIStatus.FAILED,
            CIStatus.SKIPPED,
            CIStatus.TIMED_OUT,
        )


class CIPipelineProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def trigger(self, branch: str, *, commit_sha: str | None = None) -> CIRunResult: ...

    @abstractmethod
    async def get_status(self, run_id: str) -> CIRunResult: ...

    @abstractmethod
    async def get_logs(self, run_id: str) -> str: ...

    async def wait(self, run_id: str, *, timeout_seconds: int = 900, poll_seconds: int = 10) -> CIRunResult:
        """Poll until the run finishes (section 26 - webhook or polling)."""
        import asyncio
        import time

        deadline = time.monotonic() + timeout_seconds
        while True:
            result = await self.get_status(run_id)
            if result.finished:
                return result
            if time.monotonic() >= deadline:
                return CIRunResult(id=run_id, status=CIStatus.TIMED_OUT, url=result.url)
            await asyncio.sleep(poll_seconds)

    async def close(self) -> None:  # pragma: no cover - adapters override
        return None
