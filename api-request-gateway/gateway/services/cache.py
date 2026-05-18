from __future__ import annotations

import hashlib
import json
from typing import Any

import redis.asyncio as redis

from gateway.config import get_settings


def stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def analyze_cache_key(task_description: str, code: str) -> str:
    payload = stable_json({"task_description": task_description, "code": code})
    return f"cache:analyze:{sha256_hex(payload)}"


def generate_cache_key(tags: list[str], difficulty: str) -> str:
    payload = stable_json({"tags": sorted(tags), "difficulty": difficulty})
    return f"cache:generate:{sha256_hex(payload)}"


def pipeline_cache_key(task_description: str, code: str) -> str:
    payload = stable_json({"task_description": task_description, "code": code})
    return f"cache:pipeline:{sha256_hex(payload)}"


class CacheService:
    def __init__(self, r: redis.Redis):
        self._r = r

    async def get_json(self, key: str) -> dict[str, Any] | None:
        raw = await self._r.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: dict[str, Any]) -> None:
        ttl = get_settings().cache_ttl_seconds
        await self._r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
