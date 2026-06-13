from __future__ import annotations

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request

from db.models import Platform
from gateway.schemas.auth import AuthRegisterResponse, TokenRequest, TokenResponse
from gateway.services.auth import check_rate_limit, verify_api_key
from gateway.services.users import get_user_for_platform, issue_token_for_user, register_user

router = APIRouter()


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


@router.post(
    "/auth/register",
    response_model=AuthRegisterResponse,
    tags=["Авторизация"],
    summary="Регистрация пользователя платформой",
)
async def register(
    platform: Platform = Depends(verify_api_key),
    r: redis.Redis = Depends(get_redis),
) -> AuthRegisterResponse:
    """Register a new user (UUID) for the platform. Called by LitCode backend on student signup."""
    await check_rate_limit(r, platform_id=platform.id)
    user, token = await register_user(platform)
    return AuthRegisterResponse(user_id=user.id, access_token=token)


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["Авторизация"],
    summary="Перевыпуск JWT для пользователя",
)
async def issue_token(
    body: TokenRequest,
    platform: Platform = Depends(verify_api_key),
    r: redis.Redis = Depends(get_redis),
) -> TokenResponse:
    """Re-issue JWT for an existing registered user (platform backend or refresh flow)."""
    await check_rate_limit(r, platform_id=platform.id)
    user = await get_user_for_platform(body.user_id, platform.id)
    if user is None:
        raise HTTPException(status_code=404, detail="Неизвестный user_id")
    token = await issue_token_for_user(user)
    return TokenResponse(access_token=token, user_id=user.id)
