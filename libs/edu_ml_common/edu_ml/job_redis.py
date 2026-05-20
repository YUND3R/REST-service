from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class JobRedisConfig:
    url: str
    key_prefix: str
    ttl_seconds: int = 86400


class AsyncJobStore:
    def __init__(self, cfg: JobRedisConfig, client: aioredis.Redis):
        self._cfg = cfg
        self._r = client

    def _key(self, job_id: str) -> str:
        return f"{self._cfg.key_prefix}{job_id}"

    async def _get_raw(self, job_id: str) -> dict[str, Any] | None:
        raw = await self._r.get(self._key(job_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def create_pending(self, job_id: str) -> None:
        doc = {"status": "pending", "result": None, "error": None, "created_at": _now_iso(), "updated_at": _now_iso()}
        await self._r.set(self._key(job_id), json.dumps(doc, ensure_ascii=False), ex=self._cfg.ttl_seconds)

    async def get_doc(self, job_id: str) -> dict[str, Any] | None:
        return await self._get_raw(job_id)


def make_job_id() -> str:
    return str(uuid.uuid4())
