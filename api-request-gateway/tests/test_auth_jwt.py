from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient

from conftest import TEST_API_KEY
from db.models import Platform, User
from gateway.services.auth import AuthContext, create_access_token, verify_auth_context
from gateway.services.queue import QueueService

STUDENT_ID = "a0000000-0000-4000-8000-000000000099"


@pytest.mark.asyncio
async def test_analyze_with_jwt_token(
    gateway_app: tuple[TestClient, QueueService, object],
    test_platform: Platform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, queue, app = gateway_app
    user_id = uuid.UUID(STUDENT_ID)
    token = create_access_token(user_id=user_id, platform_id=test_platform.id)

    async def override_auth_context() -> AuthContext:
        return AuthContext(platform=test_platform, user_id=user_id)

    app.dependency_overrides[verify_auth_context] = override_auth_context

    resp = client.post(
        "/api/v1/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "student_id": STUDENT_ID,
            "task_description": "Sum two numbers",
            "code": "def add(a, b):\n    return a + b",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    app.dependency_overrides.pop(verify_auth_context, None)


def test_student_id_must_be_uuid(gateway_client: tuple[TestClient, QueueService, Platform]) -> None:
    client, _queue, _platform = gateway_client

    resp = client.post(
        "/api/v1/analyze",
        headers={"X-API-Key": TEST_API_KEY},
        json={
            "student_id": "not-a-uuid",
            "task_description": "t",
            "code": "c",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 422


def test_jwt_student_id_mismatch_forbidden(
    gateway_app: tuple[TestClient, QueueService, object],
    test_platform: Platform,
) -> None:
    client, _queue, app = gateway_app
    user_id = uuid.uuid4()
    other_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, platform_id=test_platform.id)

    async def override_auth_context() -> AuthContext:
        return AuthContext(platform=test_platform, user_id=user_id)

    app.dependency_overrides[verify_auth_context] = override_auth_context

    resp = client.post(
        "/api/v1/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "student_id": str(other_id),
            "task_description": "t",
            "code": "c",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 403
    app.dependency_overrides.pop(verify_auth_context, None)


@pytest.mark.asyncio
async def test_analyze_with_real_jwt_verify_auth(
    gateway_app: tuple[TestClient, QueueService, object],
    test_platform: Platform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end JWT path without overriding verify_auth_context."""
    client, queue, app = gateway_app
    user_id = uuid.UUID(STUDENT_ID)
    token = create_access_token(user_id=user_id, platform_id=test_platform.id)

    async def fake_get_platform(platform_id: uuid.UUID) -> Platform | None:
        return test_platform if platform_id == test_platform.id else None

    monkeypatch.setattr("gateway.services.auth.get_platform_by_id", fake_get_platform)
    app.dependency_overrides.pop(verify_auth_context, None)

    resp = client.post(
        "/api/v1/analyze",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "student_id": STUDENT_ID,
            "task_description": "Sum two numbers",
            "code": "def add(a, b):\n    return a + b",
            "webhook_url": "https://httpbin.org/post",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_register_requires_api_key(gateway_app: tuple[TestClient, QueueService, object]) -> None:
    client, _queue, _app = gateway_app
    resp = client.post("/api/v1/auth/register")
    assert resp.status_code == 401


def test_issue_token_unknown_user(
    gateway_app: tuple[TestClient, QueueService, object],
    test_platform: Platform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _queue, app = gateway_app

    async def override_api_key() -> Platform:
        return test_platform

    from gateway.services.auth import verify_api_key

    app.dependency_overrides[verify_api_key] = override_api_key

    async def fake_get_user(_user_id: uuid.UUID, _platform_id: uuid.UUID) -> User | None:
        return None

    monkeypatch.setattr("gateway.routers.auth.get_user_for_platform", fake_get_user)

    resp = client.post(
        "/api/v1/auth/token",
        headers={"X-API-Key": TEST_API_KEY},
        json={"user_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    app.dependency_overrides.pop(verify_api_key, None)
