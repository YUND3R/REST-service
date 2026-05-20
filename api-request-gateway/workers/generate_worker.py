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

from db.models import GeneratedTask
from db.session import get_session_factory
from gateway.config import get_settings
from gateway.services.cache import CacheService
from gateway.services.queue import STATUS_FAILED, STATUS_PROCESSING, QueueService
from gateway.services.webhook import deliver_webhook
from models.broken_code_gen import BrokenCodeGenModel

logger = logging.getLogger(__name__)


async def persist_generated(
    student_uuid: uuid.UUID,
    tags: list[str],
    difficulty: str,
    task_blob: dict[str, Any],
    analysis_id: uuid.UUID | None,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = GeneratedTask(
            student_id=student_uuid,
            analysis_id=analysis_id,
            tags=tags,
            difficulty=difficulty,
            task_json=task_blob,
        )
        session.add(row)
        await session.commit()


class GenerateWorker:
    def __init__(self, model: BrokenCodeGenModel) -> None:
        self._settings = get_settings()
        self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
        self._queue = QueueService(self._redis)
        self._cache = CacheService(self._redis)
        self._model = model
        self._stream = self._settings.stream_generate
        self._group = os.environ.get("STREAM_GROUP_GENERATE", "generate_workers")
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
                        logger.exception("generate job failed: %s", e)
                        if job.get("task_id"):
                            await self._queue.set_status(str(job["task_id"]), STATUS_FAILED, error=str(e))
                        await self._redis.xack(self._stream, self._group, msg_id)

    async def _handle_job(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(job["student_uuid"])
        tags = list(job["tags"])
        difficulty = str(job["difficulty"])
        webhook_url = str(job["webhook_url"])
        cache_key = str(job["cache_key"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)

        cached = await self._cache.get_json(cache_key)
        if cached is not None:
            out = cached
        else:
            out = await asyncio.to_thread(self._model.infer_sync, tags, difficulty)
            await self._cache.set_json(cache_key, out)

        await persist_generated(student_uuid, tags, difficulty, out, None)

        body = {"student_id": student_external, "generated_task": out}
        await self._queue.complete_with_result(task_id, body)
        await deliver_webhook(webhook_url, body, timeout=60.0)


async def amain() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    m = BrokenCodeGenModel()
    m.ensure_loaded()
    w = GenerateWorker(m)
    await w.run_forever()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
