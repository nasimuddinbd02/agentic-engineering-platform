"""API integration tests (sections 15, 29, 52 and 56).

Exercises the real FastAPI app against SQLite and the in-process queue: create
a task, get 202, see it queued, replay the idempotency key, read the timeline,
approve and reject.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api import dependencies as api_dependencies
from apps.api.main import create_app
from core.config import Settings
from core.domain import TaskStatus
from infrastructure import build_coordination, reset_coordination
from persistence.db import create_schema, dispose_engine, session_scope
from persistence.repositories import TaskRepository


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    await reset_coordination()
    await api_dependencies.reset_coordination_cache()

    # Point the app's dependencies at the per-test settings.
    original = api_dependencies.get_settings
    api_dependencies.get_settings = lambda: settings  # type: ignore[assignment]
    import core.config as config_module

    original_cached = config_module.get_settings
    config_module.get_settings = lambda: settings  # type: ignore[assignment]

    await create_schema(settings)
    application = create_app()
    # Skip the lifespan (it would re-resolve global settings); the schema and
    # coordination are already prepared above.
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    api_dependencies.get_settings = original  # type: ignore[assignment]
    config_module.get_settings = original_cached  # type: ignore[assignment]
    await dispose_engine()
    await reset_coordination()
    await api_dependencies.reset_coordination_cache()


ISSUE = "Cancelling an already cancelled order returns HTTP 500 instead of succeeding."


async def test_health_live(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_health_ready_reports_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200
    checks = response.json()["checks"]
    assert checks["database"] == "ok"
    assert checks["coordination"] == "memory"


async def test_create_task_returns_202_and_queues(client: AsyncClient, settings: Settings) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"repository": "file://order-service", "issue": ISSUE, "created_by": "dev"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == TaskStatus.QUEUED.value
    task_id = body["task_id"]

    async with session_scope(settings) as session:
        task = await TaskRepository(session).get(task_id)
        assert task is not None
        assert task.issue == ISSUE
        assert task.created_by == "dev"

    # The handler returned before the agent ran; the id is on the queue instead.
    queue = build_coordination(settings).queue
    queued = await queue.receive(timeout_seconds=2.0)
    assert queued is not None and queued.task_id == task_id


async def test_idempotency_key_replays_the_same_task(client: AsyncClient) -> None:
    payload = {"repository": "file://order-service", "issue": ISSUE}
    headers = {"Idempotency-Key": "abc-123"}

    first = await client.post("/api/v1/tasks", json=payload, headers=headers)
    second = await client.post("/api/v1/tasks", json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 200, "a replay must not create a second task"
    assert first.json()["task_id"] == second.json()["task_id"]


async def test_idempotency_key_reuse_with_different_body_conflicts(client: AsyncClient) -> None:
    headers = {"Idempotency-Key": "shared-key"}
    await client.post(
        "/api/v1/tasks", json={"repository": "file://a", "issue": ISSUE}, headers=headers
    )
    conflict = await client.post(
        "/api/v1/tasks",
        json={"repository": "file://b", "issue": "A completely different issue entirely."},
        headers=headers,
    )
    assert conflict.status_code == 409


async def test_task_detail_and_timeline(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/tasks", json={"repository": "file://order-service", "issue": ISSUE}
    )
    task_id = created.json()["task_id"]

    detail = await client.get(f"/api/v1/tasks/{task_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["task"]["task_id"] == task_id
    assert [event["type"] for event in body["events"]] == ["TASK_CREATED"]
    assert body["runs"] == []


async def test_unknown_task_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/tasks/TASK-nope")).status_code == 404
    assert (await client.get("/api/v1/tasks/TASK-nope/diff")).status_code == 404


async def test_approve_requires_ready_for_review(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/tasks", json={"repository": "file://order-service", "issue": ISSUE}
    )
    task_id = created.json()["task_id"]

    rejected = await client.post(f"/api/v1/tasks/{task_id}/approve", json={"decided_by": "dev"})
    assert rejected.status_code == 409, "a QUEUED task cannot be approved"


async def test_approval_flow(client: AsyncClient, settings: Settings) -> None:
    created = await client.post(
        "/api/v1/tasks", json={"repository": "file://order-service", "issue": ISSUE}
    )
    task_id = created.json()["task_id"]

    async with session_scope(settings) as session:
        await TaskRepository(session).set_status(task_id, TaskStatus.READY_FOR_REVIEW)

    pending = await client.get("/api/v1/approvals")
    assert task_id in [item["task_id"] for item in pending.json()]

    approved = await client.post(
        f"/api/v1/tasks/{task_id}/approve", json={"decided_by": "reviewer", "reason": "looks good"}
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == TaskStatus.COMPLETED.value

    detail = await client.get(f"/api/v1/tasks/{task_id}")
    types = [event["type"] for event in detail.json()["events"]]
    assert "APPROVAL_GRANTED" in types
    assert "TASK_COMPLETED" in types
    # This task never ran the workflow, so there is no approval row to decide;
    # the record path is covered end to end in tests/graph.
    assert detail.json()["approvals"] == []


async def test_reject_flow(client: AsyncClient, settings: Settings) -> None:
    created = await client.post(
        "/api/v1/tasks", json={"repository": "file://order-service", "issue": ISSUE}
    )
    task_id = created.json()["task_id"]
    async with session_scope(settings) as session:
        await TaskRepository(session).set_status(task_id, TaskStatus.READY_FOR_REVIEW)

    response = await client.post(
        f"/api/v1/tasks/{task_id}/reject", json={"decided_by": "reviewer", "reason": "wrong fix"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == TaskStatus.REJECTED.value


async def test_cancel_flow(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/tasks", json={"repository": "file://order-service", "issue": ISSUE}
    )
    task_id = created.json()["task_id"]

    response = await client.post(f"/api/v1/tasks/{task_id}/cancel", json={"reason": "not needed"})
    assert response.json()["status"] == TaskStatus.CANCELLED.value

    again = await client.post(f"/api/v1/tasks/{task_id}/cancel", json={})
    assert again.status_code == 409


async def test_policies_endpoint_exposes_the_rules(client: AsyncClient) -> None:
    response = await client.get("/api/v1/policies")
    names = [rule["name"] for rule in response.json()]
    assert "block-secrets" in names
    assert "sensitive-auth" in names
