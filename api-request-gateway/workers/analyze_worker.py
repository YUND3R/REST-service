from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

from db.models import Analysis
from db.session import get_session_factory
from gateway.config import get_settings
from gateway.services.cache import CacheService
from gateway.services.queue import STATUS_FAILED, STATUS_PROCESSING, QueueService
from gateway.services.webhook import deliver_webhook
from models.code_analyze import CodeAnalyzeModel

logger = logging.getLogger(__name__)


async def persist_analysis(
    student_uuid: uuid.UUID,
    task_description: str,
    code: str,
    analysis: dict[str, Any],
) -> uuid.UUID:
    factory = get_session_factory()
    async with factory() as session:
        row = Analysis(
            student_id=student_uuid,
            task_description=task_description,
            code=code,
            score=analysis.get("score"),
            weak_spots=analysis.get("weak_spots"),
            tags=analysis.get("tags"),
            recommendations=analysis.get("recommendations"),
        )
        session.add(row)
        await session.flush()
        aid = row.id
        await session.commit()
        return aid


class AnalyzeWorker:
    def __init__(self, model: CodeAnalyzeModel) -> None:
        self._settings = get_settings()
        self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
        self._queue = QueueService(self._redis)
        self._cache = CacheService(self._redis)
        self._model = model
        self._stream = self._settings.stream_analyze
        self._group = os.environ.get("STREAM_GROUP_ANALYZE", "analyze_workers")
        self._consumer = os.environ.get("CONSUMER_NAME", socket.gethostname())

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0-0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run_forever(self) -> None:
        await self.ensure_group()
        while True:
            resp = await self._redis.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: ">"},
                count=int(os.environ.get("STREAM_BATCH", "4")),
                block=5000,
            )
            if not resp:
                continue
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    job: dict[str, Any] = {}
                    try:
                        raw = fields.get("data") or "{}"
                        job = json.loads(raw)
                        await self._handle_job(job)
                        await self._redis.xack(self._stream, self._group, msg_id)
                    except Exception as e:
                        logger.exception("analyze job failed: %s", e)
                        if job.get("task_id"):
                            await self._queue.set_status(str(job["task_id"]), STATUS_FAILED, error=str(e))
                        await self._redis.xack(self._stream, self._group, msg_id)

    async def _handle_job(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(job["student_uuid"])
        task_description = str(job["task_description"])
        code = str(job["code"])
        webhook_url = str(job["webhook_url"])
        cache_key = str(job["cache_key"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)

        cached = await self._cache.get_json(cache_key)
        if cached is not None:
            analysis = cached
        else:
            analysis = await asyncio.to_thread(self._model.infer_sync, task_description, code)
            await self._cache.set_json(cache_key, analysis)

        await persist_analysis(student_uuid, task_description, code, analysis)

        body: dict[str, Any] = {"student_id": student_external, "analysis": analysis}
        await self._queue.complete_with_result(task_id, body)
        await deliver_webhook(webhook_url, body, timeout=60.0)


async def amain() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    m = CodeAnalyzeModel()
    m.ensure_loaded()
    w = AnalyzeWorker(m)
    await w.run_forever()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
