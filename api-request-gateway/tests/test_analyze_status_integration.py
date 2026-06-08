from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from db.models import Platform
from gateway.services.queue import QueueService
from tests.conftest import TEST_API_KEY


@pytest.mark.asyncio
async def test_analyze_returns_pending_then_status_done(
    gateway_client: tuple[TestClient, QueueService, Platform],
) -> None:
    client, queue, _platform = gateway_client

    analyze_resp = client.post(
        "/api/v1/analyze",
        headers={"X-API-Key": TEST_API_KEY},
        json={
            "student_id": "student-integration-1",
            "task_description": "Sum two numbers",
            "code": "def add(a, b):\n    return a + b",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert analyze_resp.status_code == 200
    body = analyze_resp.json()
    assert body["status"] == "pending"
    task_id = body["task_id"]
    uuid.UUID(task_id)

    pending_resp = client.get(
        f"/api/v1/status/{task_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert pending_resp.status_code == 200
    assert pending_resp.json()["status"] == "pending"
    assert pending_resp.json().get("result") is None

    await queue.complete_with_result(
        task_id,
        {
            "student_id": "student-integration-1",
            "analysis": {"score": 8, "tags": ["functions"], "weak_spots": []},
        },
    )

    done_resp = client.get(
        f"/api/v1/status/{task_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert done_resp.status_code == 200
    done_body = done_resp.json()
    assert done_body["status"] == "done"
    assert done_body["result"]["analysis"]["score"] == 8


def test_status_unknown_task_returns_404(
    gateway_client: tuple[TestClient, QueueService, Platform],
) -> None:
    client, _queue, _platform = gateway_client
    missing_id = str(uuid.uuid4())

    resp = client.get(
        f"/api/v1/status/{missing_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown task_id"


def test_analyze_requires_api_key(gateway_app: tuple[TestClient, QueueService, object]) -> None:
    client, _queue, _app = gateway_app

    resp = client.post(
        "/api/v1/analyze",
        json={
            "student_id": "s",
            "task_description": "t",
            "code": "c",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 401
