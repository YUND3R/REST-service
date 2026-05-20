from __future__ import annotations

import ipaddress
import os
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

Difficulty = Literal["easy", "medium", "hard"]

MAX_STUDENT_ID_LEN = 255
MAX_TASK_DESCRIPTION_LEN = 20_000
MAX_CODE_LEN = 200_000
MAX_TAG_LEN = 128
MAX_TAGS = 32


def _allowed_webhook_hosts() -> set[str]:
    raw = os.getenv("WEBHOOK_ALLOWED_HOSTS", "").strip()
    return {host.strip().lower() for host in raw.split(",") if host.strip()}


def _validate_webhook_url(url: HttpUrl) -> HttpUrl:
    host = (url.host or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("webhook_url host is required")
    if host in {"localhost"} or host.endswith(".localhost"):
        raise ValueError("webhook_url must not target loopback hostnames")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved):
        raise ValueError("webhook_url must not target private or reserved IP ranges")
    allowed = _allowed_webhook_hosts()
    if allowed and host not in allowed and not any(host.endswith(f".{allowed_host}") for allowed_host in allowed):
        raise ValueError("webhook_url host is not allowed")
    return url


class AnalyzeIn(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=MAX_STUDENT_ID_LEN, description="External student identifier")
    task_description: str = Field(..., min_length=1, max_length=MAX_TASK_DESCRIPTION_LEN)
    code: str = Field(..., min_length=1, max_length=MAX_CODE_LEN)
    webhook_url: HttpUrl

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: HttpUrl) -> HttpUrl:
        return _validate_webhook_url(v)


class GenerateIn(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=MAX_STUDENT_ID_LEN)
    tags: list[str] = Field(..., min_length=1, max_length=MAX_TAGS)
    difficulty: Difficulty
    webhook_url: HttpUrl

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        out = [tag.strip() for tag in v if tag.strip()]
        if not out:
            raise ValueError("tags must contain at least one non-empty value")
        if any(len(tag) > MAX_TAG_LEN for tag in out):
            raise ValueError(f"tags must be at most {MAX_TAG_LEN} characters")
        return out

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: HttpUrl) -> HttpUrl:
        return _validate_webhook_url(v)


class PipelineIn(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=MAX_STUDENT_ID_LEN)
    task_description: str = Field(..., min_length=1, max_length=MAX_TASK_DESCRIPTION_LEN)
    code: str = Field(..., min_length=1, max_length=MAX_CODE_LEN)
    webhook_url: HttpUrl

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: HttpUrl) -> HttpUrl:
        return _validate_webhook_url(v)
