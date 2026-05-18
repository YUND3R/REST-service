from __future__ import annotations

import logging

import redis.asyncio as redis
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select

from db.models import Platform
from db.session import session_scope
from gateway.config import get_settings

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_platform_for_key(api_key: str | None) -> Platform:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    async with session_scope() as session:
        row = (await session.execute(select(Platform).where(Platform.api_key == api_key))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return row


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
) -> Platform:
    return await get_platform_for_key(api_key)


async def check_rate_limit(redis: redis.Redis, api_key: str) -> None:
    limit = get_settings().rate_limit_per_hour
    key = f"rate_limit:{api_key}"
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
