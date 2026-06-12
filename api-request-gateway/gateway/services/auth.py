from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import jwt
import redis.asyncio as redis
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from db.models import Platform
from db.session import session_scope
from gateway.config import get_settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthContext:
    platform: Platform
    user_id: uuid.UUID | None = None

    @property
    def is_user_auth(self) -> bool:
        return self.user_id is not None


def api_key_hash(api_key: str) -> str:
    return sha256(api_key.encode("utf-8")).hexdigest()


def api_key_fingerprint(api_key: str) -> str:
    return api_key_hash(api_key)[:16]


def create_access_token(*, user_id: uuid.UUID, platform_id: uuid.UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "platform_id": str(platform_id),
        "type": "access",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "platform_id", "exp", "type", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    try:
        user_id = uuid.UUID(str(payload["sub"]))
        platform_id = uuid.UUID(str(payload["platform_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Malformed token claims") from exc
    return user_id, platform_id


async def get_platform_for_key(api_key: str | None) -> Platform:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    lookup_key = api_key_hash(api_key)
    async with session_scope() as session:
        row = (await session.execute(select(Platform).where(Platform.api_key == lookup_key))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return row


async def get_platform_by_id(platform_id: uuid.UUID) -> Platform | None:
    async with session_scope() as session:
        return (await session.execute(select(Platform).where(Platform.id == platform_id))).scalar_one_or_none()


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> Platform:
    return await get_platform_for_key(api_key)


async def verify_auth_context(
    api_key: str | None = Security(api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(http_bearer),  # noqa: B008
) -> AuthContext:
    has_bearer = credentials is not None and credentials.scheme.lower() == "bearer"
    has_api_key = bool(api_key)
    if has_bearer and has_api_key:
        raise HTTPException(status_code=400, detail="Use either X-API-Key or Bearer token, not both")
    if has_bearer:
        user_id, platform_id = decode_access_token(credentials.credentials)
        platform = await get_platform_by_id(platform_id)
        if platform is None:
            raise HTTPException(status_code=401, detail="Unknown platform in token")
        from gateway.services.users import get_user_for_platform

        user = await get_user_for_platform(user_id, platform.id)
        if user is None:
            raise HTTPException(status_code=401, detail="Unknown or revoked user")
        return AuthContext(platform=platform, user_id=user_id)
    if has_api_key:
        platform = await get_platform_for_key(api_key)
        return AuthContext(platform=platform)
    raise HTTPException(status_code=401, detail="Missing authentication: X-API-Key or Bearer token")


def ensure_student_access(ctx: AuthContext, student_id: uuid.UUID) -> None:
    if ctx.is_user_auth and student_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="student_id does not match authenticated user")


async def check_rate_limit(
    redis: redis.Redis,
    *,
    api_key: str | None = None,
    user_id: uuid.UUID | None = None,
    platform_id: uuid.UUID | None = None,
) -> None:
    limit = get_settings().rate_limit_per_hour
    if user_id is not None:
        key = f"rate_limit:user:{user_id}"
    elif platform_id is not None:
        key = f"rate_limit:platform:{platform_id}"
    elif api_key is not None:
        key = f"rate_limit:{api_key_fingerprint(api_key)}"
    else:
        return
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.ttl(key)
    n, ttl = await pipe.execute()
    if ttl == -1:
        await redis.expire(key, 3600)
    if int(n) > limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "3600"},
        )


async def check_auth_rate_limit(r: redis.Redis, ctx: AuthContext) -> None:
    if ctx.is_user_auth:
        await check_rate_limit(r, user_id=ctx.user_id)
    else:
        await check_rate_limit(r, platform_id=ctx.platform.id)
