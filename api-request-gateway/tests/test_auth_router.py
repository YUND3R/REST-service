from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from conftest import TEST_API_KEY
from db.models import Platform, User
from gateway.schemas.auth import TokenRequest
from gateway.schemas.request import AnalyzeIn, GenerateIn, PipelineIn
from gateway.services.auth import verify_api_key
from gateway.services.queue import QueueService


def test_token_request_requires_uuid() -> None:
    with pytest.raises(ValidationError):
        TokenRequest(user_id="not-a-uuid")  # type: ignore[arg-type]


def test_analyze_in_student_id_must_be_uuid() -> None:
    with pytest.raises(ValidationError):
        AnalyzeIn(
            student_id="legacy-string-id",  # type: ignore[arg-type]
            task_description="task",
            code="print(1)",
            webhook_url="https://httpbin.org/post",
        )


def test_analyze_in_accepts_uuid_string() -> None:
    student_id = uuid.uuid4()
    body = AnalyzeIn(
        student_id=student_id,
        task_description="task",
        code="print(1)",
        webhook_url="https://httpbin.org/post",
    )
    assert body.student_id == student_id


def test_generate_in_student_id_must_be_uuid() -> None:
    with pytest.raises(ValidationError):
        GenerateIn(
            student_id=123,  # type: ignore[arg-type]
            tags=["python"],
            difficulty="easy",
            webhook_url="https://httpbin.org/post",
        )


def test_pipeline_in_student_id_must_be_uuid() -> None:
    with pytest.raises(ValidationError):
        PipelineIn(
            student_id="student-42",  # type: ignore[arg-type]
            task_description="task",
            code="pass",
            webhook_url="https://httpbin.org/post",
        )


def test_register_success(
    gateway_app: tuple[TestClient, QueueService, object],
    test_platform: Platform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _queue, app = gateway_app
    user_id = uuid.uuid4()
    token = "signed.jwt.token"

    async def override_api_key() -> Platform:
        return test_platform

    async def fake_register(platform: Platform) -> tuple[User, str]:
        assert platform.id == test_platform.id
        return User(id=user_id, platform_id=platform.id), token

    app.dependency_overrides[verify_api_key] = override_api_key
    monkeypatch.setattr("gateway.routers.auth.register_user", fake_register)

    resp = client.post("/api/v1/auth/register", headers={"X-API-Key": TEST_API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(user_id)
    assert data["access_token"] == token
    assert data["token_type"] == "bearer"
    app.dependency_overrides.pop(verify_api_key, None)


def test_issue_token_success(
    gateway_app: tuple[TestClient, QueueService, object],
    test_platform: Platform,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _queue, app = gateway_app
    user_id = uuid.uuid4()
    user = User(id=user_id, platform_id=test_platform.id)

    async def override_api_key() -> Platform:
        return test_platform

    async def fake_get_user(uid: uuid.UUID, platform_id: uuid.UUID) -> User | None:
        if uid == user_id and platform_id == test_platform.id:
            return user
        return None

    async def fake_issue_token(u: User) -> str:
        assert u.id == user_id
        return "reissued.jwt.token"

    app.dependency_overrides[verify_api_key] = override_api_key
    monkeypatch.setattr("gateway.routers.auth.get_user_for_platform", fake_get_user)
    monkeypatch.setattr("gateway.routers.auth.issue_token_for_user", fake_issue_token)

    resp = client.post(
        "/api/v1/auth/token",
        headers={"X-API-Key": TEST_API_KEY},
        json={"user_id": str(user_id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(user_id)
    assert data["access_token"] == "reissued.jwt.token"
    app.dependency_overrides.pop(verify_api_key, None)
