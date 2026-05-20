from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from edu_ml.auth_jwt import decode_access_token
from edu_ml.settings_auth import get_auth_settings
from edu_ml.user_id import normalize_user_id


@dataclass
class Principal:
    method: str
    sub: str | None = None


@dataclass
class ApiContext:
    principal: Principal
    user_id: str | None


def _authenticate(request: Request) -> Principal:
    s = get_auth_settings()
    if not s.auth_enabled:
        return Principal(method="none")
    api_key = request.headers.get("X-API-Key")
    if api_key and api_key in s.parsed_api_keys():
        return Principal(method="api_key")
    auth = request.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        payload = decode_access_token(token)
        if payload and isinstance(payload.get("sub"), str) and payload["sub"].strip():
            return Principal(method="jwt", sub=payload["sub"].strip())
    raise HTTPException(
        status_code=401, detail="Нужен JWT Bearer или X-API-Key", headers={"WWW-Authenticate": "Bearer"}
    )


def get_api_context(request: Request, x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> ApiContext:
    s = get_auth_settings()
    principal = _authenticate(request)
    try:
        if not s.auth_enabled:
            if not x_user_id or not str(x_user_id).strip():
                return ApiContext(principal, None)
            uid = normalize_user_id(str(x_user_id).strip())
            return ApiContext(principal, uid)
        if principal.method == "jwt" and principal.sub:
            return ApiContext(principal, principal.sub)
        if principal.method == "api_key":
            if not x_user_id or not str(x_user_id).strip():
                return ApiContext(principal, None)
            uid = normalize_user_id(str(x_user_id).strip())
            return ApiContext(principal, uid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    raise HTTPException(status_code=401, detail="Некорректная аутентификация")


def optional_uid(ctx: Annotated[ApiContext, Depends(get_api_context)]) -> str | None:
    return ctx.user_id


def required_uid(ctx: Annotated[ApiContext, Depends(get_api_context)]) -> str:
    if not ctx.user_id:
        s = get_auth_settings()
        if s.auth_enabled:
            raise HTTPException(
                status_code=400, detail="Для API key укажите X-User-Id; для JWT поле sub задаёт пользователя"
            )
        raise HTTPException(status_code=400, detail="Нужен заголовок X-User-Id")
    return ctx.user_id
