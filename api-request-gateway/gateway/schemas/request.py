from __future__ import annotations

import ipaddress
import os
import uuid
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

Difficulty = Literal["easy", "medium", "hard"]

MAX_TASK_DESCRIPTION_LEN = 20_000
MAX_CODE_LEN = 200_000
MAX_TAG_LEN = 128
MAX_TAGS = 32


def _allowed_webhook_hosts() -> set[str]:
    raw = os.getenv("WEBHOOK_ALLOWED_HOSTS", "").strip()
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def _validate_webhook_url(url: HttpUrl) -> HttpUrl:
    env = os.getenv("ENVIRONMENT", "").strip().lower()
    if env == "production" and url.scheme != "https":
        raise ValueError("В production поле webhook_url должно использовать https")
    host = (url.host or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("В webhook_url должен быть указан host")
    if host in {"localhost"} or host.endswith(".localhost"):
        raise ValueError("webhook_url не должен указывать на loopback-имена")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved):
        raise ValueError("webhook_url не должен указывать на private/reserved диапазоны IP")
    allowed = _allowed_webhook_hosts()
    if allowed and host not in allowed and not any(host.endswith(f".{allowed_host}") for allowed_host in allowed):
        raise ValueError("Host из webhook_url не входит в список разрешенных")
    return url


class AnalyzeIn(BaseModel):
    student_id: uuid.UUID = Field(..., description="Registered user UUID")
    task_description: str = Field(..., min_length=1, max_length=MAX_TASK_DESCRIPTION_LEN)
    code: str = Field(..., min_length=1, max_length=MAX_CODE_LEN)
    webhook_url: HttpUrl

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: HttpUrl) -> HttpUrl:
        return _validate_webhook_url(v)


class GenerateIn(BaseModel):
    student_id: uuid.UUID = Field(..., description="Registered user UUID")
    tags: list[str] = Field(..., min_length=1, max_length=MAX_TAGS)
    difficulty: Difficulty
    webhook_url: HttpUrl

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        out = [tag.strip() for tag in v if tag.strip()]
        if not out:
            raise ValueError("Список tags должен содержать хотя бы одно непустое значение")
        if any(len(tag) > MAX_TAG_LEN for tag in out):
            raise ValueError(f"Каждый tag должен быть не длиннее {MAX_TAG_LEN} символов")
        return out

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: HttpUrl) -> HttpUrl:
        return _validate_webhook_url(v)


class PipelineIn(BaseModel):
    student_id: uuid.UUID = Field(..., description="Registered user UUID")
    task_description: str = Field(..., min_length=1, max_length=MAX_TASK_DESCRIPTION_LEN)
    code: str = Field(..., min_length=1, max_length=MAX_CODE_LEN)
    webhook_url: HttpUrl

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: HttpUrl) -> HttpUrl:
        return _validate_webhook_url(v)
