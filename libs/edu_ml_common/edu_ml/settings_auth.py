from __future__ import annotations
from functools import lru_cache
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')
    auth_enabled: bool = False
    jwt_secret: str = Field(default='')
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 60
    auth_credentials: str | None = None
    auth_api_keys: str | None = None

    @model_validator(mode='after')
    def require_jwt_secret_if_auth(self) -> AuthSettings:
        if self.auth_enabled and len(self.jwt_secret.strip()) < 8:
            raise ValueError('При AUTH_ENABLED=true задайте JWT_SECRET в окружении (не короче 8 символов).')
        return self

    def parsed_passwords(self) -> dict[str, str]:
        if not self.auth_credentials:
            return {}
        out: dict[str, str] = {}
        for part in self.auth_credentials.split(';'):
            part = part.strip()
            if not part or ':' not in part:
                continue
            user, pw = part.split(':', 1)
            out[user.strip()] = pw.strip()
        return out

    def parsed_api_keys(self) -> frozenset[str]:
        if not self.auth_api_keys:
            return frozenset()
        keys = [k.strip() for k in self.auth_api_keys.split(',') if k.strip()]
        return frozenset(keys)

@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
