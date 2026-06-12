from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "API Request Gateway"
    app_version: str = "1.0.0"
    environment: str = "development"

    log_level: str = "INFO"
    redis_url: str = "redis://redis:6379/0"
    database_url: str = "postgresql+asyncpg://ai_mentor:CHANGE_ME@postgres:5432/ai_mentor"

    rate_limit_per_hour: int = 1000
    cache_ttl_seconds: int = 24 * 3600
    docs_enabled: bool = False

    cors_origins: str = "https://app.example.com"
    webhook_allowed_hosts: str = ""

    stream_analyze: str = "queue:analyze"
    stream_generate: str = "queue:generate"
    stream_pipeline: str = "queue:pipeline"
    stream_webhook: str = "queue:webhook"

    jwt_secret: str = "dev-jwt-secret-at-least-32-chars-long!!"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_issuer: str = "api-request-gateway"
    jwt_audience: str = "litcode-student"

    @field_validator("docs_enabled", mode="before")
    @classmethod
    def _bool_from_str(cls, v: object) -> object:
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes", "on")
        return v

    @model_validator(mode="after")
    def _validate_jwt_secret_in_production(self) -> Self:
        if self.environment == "production" and len(self.jwt_secret.strip()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters when ENVIRONMENT=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
