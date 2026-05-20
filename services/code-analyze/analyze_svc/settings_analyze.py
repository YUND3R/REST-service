from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AnalyzeServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    local_model_path: str = "/opt/models"
    preload_model: bool = True
    max_new_tokens: int = 4096
    sqs_analyze_queue_url: str | None = None
    aws_region: str | None = None
    sqs_visibility_timeout_seconds: int = 900
    job_result_ttl_seconds: int = 86400
    redis_url: str | None = None
    redis_ttl_seconds: int | None = None
    user_history_max: int = 0
    cors_origins: str = "https://app.example.com"


@lru_cache
def get_analyze_settings() -> AnalyzeServiceSettings:
    return AnalyzeServiceSettings()
