from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

import redis.asyncio as redis

from gateway.config import get_settings

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def status_key(task_id: str) -> str:
    return f"status:{task_id}"


def result_key(task_id: str) -> str:
    return f"result:{task_id}"


class QueueService:
    def __init__(self, r: redis.Redis):
        self._r = r

    async def set_status(self, task_id: str, status: str, *, error: str | None = None) -> None:
        doc = {"status": status, "updated_at": time.time()}
        if error:
            doc["error"] = error
        await self._r.set(status_key(task_id), json.dumps(doc, ensure_ascii=False), ex=get_settings().cache_ttl_seconds)

    async def set_result(self, task_id: str, result: dict[str, Any]) -> None:
        await self._r.set(
            result_key(task_id),
            json.dumps(result, ensure_ascii=False),
            ex=get_settings().cache_ttl_seconds,
        )

    async def get_snapshot(self, task_id: str) -> dict[str, Any] | None:
        st_raw = await self._r.get(status_key(task_id))
        if not st_raw:
            return None
        try:
            st = json.loads(st_raw)
        except json.JSONDecodeError:
            st = {"status": STATUS_PENDING}
        res_raw = await self._r.get(result_key(task_id))
        out: dict[str, Any] = {"task_id": task_id, **st}
        if res_raw:
            try:
                out["result"] = json.loads(res_raw)
            except json.JSONDecodeError:
                out["result"] = None
        return out

    async def ensure_stream(self, stream: str) -> None:
        try:
            await self._r.xgroup_create(stream, self._default_group(stream), id="0-0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def _default_group(self, stream: str) -> str:
        s = get_settings()
        if stream == s.stream_analyze:
            return "analyze_workers"
        if stream == s.stream_generate:
            return "generate_workers"
        return "pipeline_workers"

    async def enqueue_analyze(self, payload: dict[str, Any], *, task_id: str | None = None) -> str:
        s = get_settings()
        tid = task_id or str(uuid.uuid4())
        await self.set_status(tid, STATUS_PENDING)
        body = {"task_id": tid, **payload}
        await self._r.xadd(s.stream_analyze, {"data": json.dumps(body, ensure_ascii=False)})
        await self.ensure_stream(s.stream_analyze)
        logger.debug("Enqueued analyze: %s", tid)
        return tid

    async def enqueue_generate(self, payload: dict[str, Any], *, task_id: str | None = None) -> str:
        s = get_settings()
        tid = task_id or str(uuid.uuid4())
        await self.set_status(tid, STATUS_PENDING)
        body = {"task_id": tid, **payload}
        await self._r.xadd(s.stream_generate, {"data": json.dumps(body, ensure_ascii=False)})
        await self.ensure_stream(s.stream_generate)
        return tid

    async def enqueue_pipeline(self, payload: dict[str, Any], *, task_id: str | None = None) -> str:
        s = get_settings()
        tid = task_id or str(uuid.uuid4())
        await self.set_status(tid, STATUS_PENDING)
        body = {"task_id": tid, **payload}
        await self._r.xadd(s.stream_pipeline, {"data": json.dumps(body, ensure_ascii=False)})
        await self.ensure_stream(s.stream_pipeline)
        return tid

    async def complete_with_result(self, task_id: str, result: dict[str, Any]) -> None:
        await self.set_status(task_id, STATUS_DONE)
        await self.set_result(task_id, result)
