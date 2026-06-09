from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from conftest import TEST_API_KEY
from db.models import Platform
from gateway.services.queue import QueueService


@pytest.mark.asyncio
async def test_generate_returns_pending_then_status_done(
    gateway_client: tuple[TestClient, QueueService, Platform],
) -> None:
    client, queue, _platform = gateway_client

    generate_resp = client.post(
        "/api/v1/generate",
        headers={"X-API-Key": TEST_API_KEY},
        json={
            "student_id": "student-integration-2",
            "tags": ["graphs"],
            "difficulty": "easy",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert generate_resp.status_code == 200
    body = generate_resp.json()
    assert body["status"] == "pending"
    task_id = body["task_id"]
    uuid.UUID(task_id)

    pending_resp = client.get(
        f"/api/v1/status/{task_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert pending_resp.status_code == 200
    assert pending_resp.json()["status"] == "pending"

    await queue.complete_with_result(
        task_id,
        {
            "student_id": "student-integration-2",
            "generated_task": {
                "title": "Fix add_one",
                "difficulty": "easy",
                "broken_code": "def add_one(n):\n    return n - 1\n",
            },
        },
    )

    done_resp = client.get(
        f"/api/v1/status/{task_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert done_resp.status_code == 200
    done_body = done_resp.json()
    assert done_body["status"] == "done"
    assert done_body["result"]["generated_task"]["difficulty"] == "easy"


@pytest.mark.asyncio
async def test_pipeline_returns_pending_then_status_done(
    gateway_client: tuple[TestClient, QueueService, Platform],
) -> None:
    client, queue, _platform = gateway_client

    pipeline_resp = client.post(
        "/api/v1/pipeline",
        headers={"X-API-Key": TEST_API_KEY},
        json={
            "student_id": "student-integration-3",
            "task_description": "Increment a number",
            "code": "def add_one(n):\n    return n - 1",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert pipeline_resp.status_code == 200
    body = pipeline_resp.json()
    assert body["status"] == "pending"
    task_id = body["task_id"]
    uuid.UUID(task_id)

    pending_resp = client.get(
        f"/api/v1/status/{task_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert pending_resp.status_code == 200
    assert pending_resp.json()["status"] == "pending"

    await queue.complete_with_result(
        task_id,
        {
            "student_id": "student-integration-3",
            "analysis": {"score": 5, "tags": ["functions"], "weak_spots": []},
            "generated_task": {"title": "Next task", "difficulty": "medium"},
            "profile_tags_used": ["functions"],
        },
    )

    done_resp = client.get(
        f"/api/v1/status/{task_id}",
        headers={"X-API-Key": TEST_API_KEY},
    )
    assert done_resp.status_code == 200
    done_body = done_resp.json()
    assert done_body["status"] == "done"
    assert done_body["result"]["analysis"]["score"] == 5
    assert done_body["result"]["generated_task"]["difficulty"] == "medium"


def test_generate_requires_api_key(gateway_app: tuple[TestClient, QueueService, object]) -> None:
    client, _queue, _app = gateway_app

    resp = client.post(
        "/api/v1/generate",
        json={
            "student_id": "s",
            "tags": ["python"],
            "difficulty": "easy",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 401


def test_pipeline_requires_api_key(gateway_app: tuple[TestClient, QueueService, object]) -> None:
    client, _queue, _app = gateway_app

    resp = client.post(
        "/api/v1/pipeline",
        json={
            "student_id": "s",
            "task_description": "t",
            "code": "c",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 401
