from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from edu_ml.settings_auth import get_auth_settings


def create_access_token(*, subject: str) -> str:
    s = get_auth_settings()
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=s.access_token_expire_minutes)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": int(expire.timestamp()), "typ": "access"}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    s = get_auth_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError:
        return None
