from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest

from db.models import Platform, Student, User
from gateway.services.auth import decode_access_token
from gateway.services.users import get_user_for_platform, issue_token_for_user, register_user


@pytest.mark.asyncio
async def test_register_user_creates_user_student_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    platform = Platform(id=uuid.uuid4(), name="litcode", api_key="hash")
    captured: list[object] = []

    class FakeSession:
        def add(self, obj: object) -> None:
            captured.append(obj)

        async def flush(self) -> None:
            return None

    @asynccontextmanager
    async def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("gateway.services.users.session_scope", fake_scope)

    user, token = await register_user(platform)

    assert isinstance(user, User)
    assert user.platform_id == platform.id
    assert len(captured) == 2
    assert isinstance(captured[0], User)
    assert isinstance(captured[1], Student)
    student = captured[1]
    assert student.id == user.id
    assert student.external_id == str(user.id)
    assert student.platform == platform.name
    assert student.platform_id == platform.id

    decoded_user, decoded_platform = decode_access_token(token)
    assert decoded_user == user.id
    assert decoded_platform == platform.id


@pytest.mark.asyncio
async def test_get_user_for_platform_found(monkeypatch: pytest.MonkeyPatch) -> None:
    platform_id = uuid.uuid4()
    user = User(id=uuid.uuid4(), platform_id=platform_id)

    class FakeResult:
        def scalar_one_or_none(self) -> User:
            return user

    class FakeSession:
        async def execute(self, _stmt: object) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("gateway.services.users.session_scope", fake_scope)
    found = await get_user_for_platform(user.id, platform_id)
    assert found is user


@pytest.mark.asyncio
async def test_get_user_for_platform_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        def scalar_one_or_none(self) -> None:
            return None

    class FakeSession:
        async def execute(self, _stmt: object) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("gateway.services.users.session_scope", fake_scope)
    found = await get_user_for_platform(uuid.uuid4(), uuid.uuid4())
    assert found is None


@pytest.mark.asyncio
async def test_issue_token_for_user() -> None:
    user = User(id=uuid.uuid4(), platform_id=uuid.uuid4())
    token = await issue_token_for_user(user)
    decoded_user, decoded_platform = decode_access_token(token)
    assert decoded_user == user.id
    assert decoded_platform == user.platform_id
