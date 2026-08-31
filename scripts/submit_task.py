"""Submit a task from the command line.

    python -m scripts.submit_task --repository-path ./.sandbox/order-service \
        --issue "Cancelling an already cancelled order returns HTTP 500."

With ``--watch`` it follows the task's event stream until the task settles,
which is the quickest way to see the control plane work without the web UI.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

TERMINAL = {
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "REJECTED",
    "HUMAN_REVIEW_REQUIRED",
    "READY_FOR_REVIEW",
}


async def submit(base_url: str, repository_path: Path, issue: str, key: str | None) -> str:
    headers = {"Idempotency-Key": key} if key else {}
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        response = await client.post(
            "/api/v1/tasks",
            json={
                "repository": repository_path.as_uri(),
                "repository_path": str(repository_path),
                "issue": issue,
            },
            headers=headers,
        )
        response.raise_for_status()
        body = response.json()
        print(f"{body['task_id']}  {body['status']}")
        return body["task_id"]


async def watch(base_url: str, task_id: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=None) as client:
        async with client.stream("GET", f"/api/v1/tasks/{task_id}/events") as response:
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    print(f"  {line.removeprefix('event: ')}")
                if "STREAM_END" in line:
                    break

    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        detail = (await client.get(f"/api/v1/tasks/{task_id}")).json()["task"]

    print("\n--- result ---")
    for field in (
        "status",
        "risk_level",
        "iteration",
        "tests_passed",
        "tests_failed",
        "ci_status",
        "branch",
        "commit_sha",
        "pull_request_url",
    ):
        print(f"{field:>18}: {detail.get(field)}")
    print(f"{'files_changed':>18}: {', '.join(detail.get('files_changed', [])) or '(none)'}")
    print(f"{'summary':>18}: {detail.get('summary') or '(none)'}")
    if detail.get("status") == "READY_FOR_REVIEW":
        print(
            f"\nApprove with:\n  curl -X POST {base_url}/api/v1/tasks/{task_id}/approve "
            '-H "Content-Type: application/json" -d \'{"decided_by":"you"}\''
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit an engineering task to the agent.")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--repository-path", type=Path, required=True)
    parser.add_argument("--issue", required=True)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--watch", action="store_true", help="follow the event stream")
    arguments = parser.parse_args()

    repository_path = arguments.repository_path.expanduser().resolve()
    if not repository_path.is_dir():
        print(f"repository path does not exist: {repository_path}", file=sys.stderr)
        return 1

    async def run() -> None:
        task_id = await submit(
            arguments.api, repository_path, arguments.issue, arguments.idempotency_key
        )
        if arguments.watch:
            await watch(arguments.api, task_id)

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
