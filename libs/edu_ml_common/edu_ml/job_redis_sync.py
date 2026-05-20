from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

import redis as sync_redis

JobStatus = Literal["pending", "processing", "completed", "failed"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SyncJobStore:
    def __init__(self, url: str, key_prefix: str, ttl_seconds: int = 86400):
        self._r = sync_redis.Redis.from_url(url, decode_responses=True)
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, job_id: str) -> str:
        return f"{self._prefix}{job_id}"

    def _load(self, job_id: str) -> dict[str, Any]:
        raw = self._r.get(self._key(job_id))
        if not raw:
            return {
                "status": "pending",
                "result": None,
                "error": None,
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
        return json.loads(raw)

    def _save(self, job_id: str, doc: dict[str, Any]) -> None:
        doc["updated_at"] = _now_iso()
        self._r.set(self._key(job_id), json.dumps(doc, ensure_ascii=False), ex=self._ttl)

    def mark_processing(self, job_id: str) -> None:
        doc = self._load(job_id)
        doc["status"] = "processing"
        self._save(job_id, doc)

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> None:
        doc = self._load(job_id)
        doc["status"] = "completed"
        doc["result"] = result
        doc["error"] = None
        self._save(job_id, doc)

    def mark_failed(self, job_id: str, error: str) -> None:
        doc = self._load(job_id)
        doc["status"] = "failed"
        doc["error"] = error
        self._save(job_id, doc)

    def close(self) -> None:
        self._r.close()
