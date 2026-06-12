from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from conftest import TEST_API_KEY, FakeRedis
from db.models import Platform
from gateway.config import get_settings
from gateway.services.auth import (
    AuthContext,
    api_key_fingerprint,
    api_key_hash,
    check_auth_rate_limit,
    check_rate_limit,
    create_access_token,
    decode_access_token,
    ensure_student_access,
    get_platform_by_id,
    get_platform_for_key,
    verify_auth_context,
)


def test_api_key_hash_is_deterministic() -> None:
    assert api_key_hash("secret-key") == api_key_hash("secret-key")
    assert api_key_hash("a") != api_key_hash("b")


def test_api_key_fingerprint_is_prefix_of_hash() -> None:
    hashed = api_key_hash("my-key")
    assert api_key_fingerprint("my-key") == hashed[:16]


def test_auth_context_user_mode_flag() -> None:
    platform = Platform(id=uuid.uuid4(), name="p", api_key="hash")
    assert AuthContext(platform=platform).is_user_auth is False
    assert AuthContext(platform=platform, user_id=uuid.uuid4()).is_user_auth is True


def test_create_and_decode_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    platform_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, platform_id=platform_id)
    decoded_user, decoded_platform = decode_access_token(token)
    assert decoded_user == user_id
    assert decoded_platform == platform_id


def test_decode_access_token_rejects_wrong_secret() -> None:
    settings = get_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "platform_id": str(uuid.uuid4()),
        "type": "access",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jwt.encode(payload, "wrong-secret", algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401


def test_decode_access_token_rejects_expired_token() -> None:
    settings = get_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "platform_id": str(uuid.uuid4()),
        "type": "access",
        "iat": datetime.now(UTC) - timedelta(hours=2),
        "exp": datetime.now(UTC) - timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert "expired" in exc_info.value.detail.lower()


def test_decode_access_token_rejects_wrong_type() -> None:
    settings = get_settings()
    payload = {
        "sub": str(uuid.uuid4()),
        "platform_id": str(uuid.uuid4()),
        "type": "refresh",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid token type"


def test_decode_access_token_rejects_malformed_claims() -> None:
    settings = get_settings()
    payload = {
        "sub": "not-a-uuid",
        "platform_id": str(uuid.uuid4()),
        "type": "access",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token(token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Malformed token claims"


def test_ensure_student_access_platform_mode_allows_any_student() -> None:
    platform = Platform(id=uuid.uuid4(), name="p", api_key="hash")
    ctx = AuthContext(platform=platform)
    ensure_student_access(ctx, uuid.uuid4())


def test_ensure_student_access_user_mode_requires_match() -> None:
    platform = Platform(id=uuid.uuid4(), name="p", api_key="hash")
    user_id = uuid.uuid4()
    ctx = AuthContext(platform=platform, user_id=user_id)
    ensure_student_access(ctx, user_id)


def test_ensure_student_access_user_mode_rejects_mismatch() -> None:
    platform = Platform(id=uuid.uuid4(), name="p", api_key="hash")
    ctx = AuthContext(platform=platform, user_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        ensure_student_access(ctx, uuid.uuid4())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_platform_for_key_missing_header() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_platform_for_key(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_platform_for_key_invalid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResult:
        def scalar_one_or_none(self) -> None:
            return None

    class FakeSession:
        async def execute(self, _stmt: object) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("gateway.services.auth.session_scope", fake_scope)
    with pytest.raises(HTTPException) as exc_info:
        await get_platform_for_key("bad-key")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_platform_for_key_valid_key(monkeypatch: pytest.MonkeyPatch) -> None:
    platform = Platform(id=uuid.uuid4(), name="litcode", api_key=api_key_hash(TEST_API_KEY))

    class FakeResult:
        def scalar_one_or_none(self) -> Platform:
            return platform

    class FakeSession:
        async def execute(self, _stmt: object) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("gateway.services.auth.session_scope", fake_scope)
    found = await get_platform_for_key(TEST_API_KEY)
    assert found.id == platform.id


@pytest.mark.asyncio
async def test_verify_auth_context_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    platform = Platform(id=uuid.uuid4(), name="litcode", api_key="hash")
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, platform_id=platform.id)

    async def fake_get_platform(platform_id: uuid.UUID) -> Platform | None:
        return platform if platform_id == platform.id else None

    monkeypatch.setattr("gateway.services.auth.get_platform_by_id", fake_get_platform)

    ctx = await verify_auth_context(
        api_key=None,
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
    )
    assert ctx.platform.id == platform.id
    assert ctx.user_id == user_id
    assert ctx.is_user_auth is True


@pytest.mark.asyncio
async def test_verify_auth_context_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    platform = Platform(id=uuid.uuid4(), name="litcode", api_key=api_key_hash(TEST_API_KEY))

    async def fake_get_platform_for_key(api_key: str | None) -> Platform:
        return platform

    monkeypatch.setattr("gateway.services.auth.get_platform_for_key", fake_get_platform_for_key)

    ctx = await verify_auth_context(api_key=TEST_API_KEY, credentials=None)
    assert ctx.platform.id == platform.id
    assert ctx.user_id is None
    assert ctx.is_user_auth is False


@pytest.mark.asyncio
async def test_verify_auth_context_missing_credentials() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await verify_auth_context(api_key=None, credentials=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_auth_context_unknown_platform_in_token(monkeypatch: pytest.MonkeyPatch) -> None:
    platform_id = uuid.uuid4()
    token = create_access_token(user_id=uuid.uuid4(), platform_id=platform_id)

    async def fake_get_platform(_platform_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr("gateway.services.auth.get_platform_by_id", fake_get_platform)

    with pytest.raises(HTTPException) as exc_info:
        await verify_auth_context(
            api_key=None,
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        )
    assert exc_info.value.status_code == 401
    assert "Unknown platform" in exc_info.value.detail


@pytest.mark.asyncio
async def test_check_rate_limit_by_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gateway.services.auth.get_settings", lambda: type("S", (), {"rate_limit_per_hour": 2})())
    fake_redis = FakeRedis()
    user_id = uuid.uuid4()
    await check_rate_limit(fake_redis, user_id=user_id)
    await check_rate_limit(fake_redis, user_id=user_id)
    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit(fake_redis, user_id=user_id)
    assert exc_info.value.status_code == 429
    assert fake_redis.strings[f"rate_limit:user:{user_id}"] == "3"


@pytest.mark.asyncio
async def test_check_auth_rate_limit_uses_user_bucket_for_jwt_auth() -> None:
    fake_redis = FakeRedis()
    user_id = uuid.uuid4()
    platform = Platform(id=uuid.uuid4(), name="p", api_key="platform-key-hash")
    ctx = AuthContext(platform=platform, user_id=user_id)
    await check_auth_rate_limit(fake_redis, ctx)
    assert f"rate_limit:user:{user_id}" in fake_redis.strings


@pytest.mark.asyncio
async def test_get_platform_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    platform = Platform(id=uuid.uuid4(), name="p", api_key="hash")

    class FakeResult:
        def scalar_one_or_none(self) -> Platform:
            return platform

    class FakeSession:
        async def execute(self, _stmt: object) -> FakeResult:
            return FakeResult()

    @asynccontextmanager
    async def fake_scope():
        yield FakeSession()

    monkeypatch.setattr("gateway.services.auth.session_scope", fake_scope)
    found = await get_platform_by_id(platform.id)
    assert found is platform
