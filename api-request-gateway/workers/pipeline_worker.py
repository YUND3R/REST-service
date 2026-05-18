from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from typing import Any

import httpx
import redis.asyncio as redis
from redis.exceptions import ResponseError

from db.models import Analysis, GeneratedTask
from db.session import get_session_factory
from gateway.config import get_settings
from gateway.services.cache import CacheService, analyze_cache_key, generate_cache_key
from gateway.services.queue import STATUS_FAILED, STATUS_PROCESSING, QueueService
from models.broken_code_gen import BrokenCodeGenModel
from models.code_analyze import CodeAnalyzeModel, score_to_difficulty

logger = logging.getLogger(__name__)


async def deliver_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
    except Exception:
        logger.exception("Webhook POST failed: %s", url)


async def persist_pipeline(
    student_uuid: uuid.UUID,
    task_description: str,
    code: str,
    analysis: dict[str, Any],
    gen: dict[str, Any],
    difficulty: str,
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        an = Analysis(
            student_id=student_uuid,
            task_description=task_description,
            code=code,
            score=analysis.get("score"),
            weak_spots=analysis.get("weak_spots"),
            tags=analysis.get("tags"),
            recommendations=analysis.get("recommendations"),
        )
        session.add(an)
        await session.flush()
        aid = an.id
        gt = GeneratedTask(
            student_id=student_uuid,
            analysis_id=aid,
            tags=list(analysis.get("tags") or []),
            difficulty=difficulty,
            task_json=gen,
        )
        session.add(gt)
        await session.commit()


class PipelineWorker:
    def __init__(self, analyze: CodeAnalyzeModel, generator: BrokenCodeGenModel) -> None:
        self._settings = get_settings()
        self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
        self._queue = QueueService(self._redis)
        self._cache = CacheService(self._redis)
        self._analyze = analyze
        self._generator = generator
        self._stream = self._settings.stream_pipeline
        self._group = os.environ.get("STREAM_GROUP_PIPELINE", "pipeline_workers")
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
                count=int(os.environ.get("STREAM_BATCH", "1")),
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
                        logger.exception("pipeline job failed: %s", e)
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
        pipeline_cache_key = str(job["cache_key"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)

        cached = await self._cache.get_json(pipeline_cache_key)
        if cached is not None:
            await self._queue.complete_with_result(task_id, cached)
            await deliver_webhook(webhook_url, cached)
            return

        ak = analyze_cache_key(task_description, code)
        analysis = await self._cache.get_json(ak)
        if analysis is None:
            analysis = await asyncio.to_thread(self._analyze.infer_sync, task_description, code)
            await self._cache.set_json(ak, analysis)

        score = int(analysis.get("score", 5))
        difficulty = score_to_difficulty(score)
        tags = list(analysis.get("tags") or [])
        if not tags:
            tags = ["general"]

        gk = generate_cache_key(tags, difficulty)
        generated = await self._cache.get_json(gk)
        if generated is None:
            generated = await asyncio.to_thread(self._generator.infer_sync, tags, difficulty)
            await self._cache.set_json(gk, generated)

        await persist_pipeline(student_uuid, task_description, code, analysis, generated, difficulty)

        body: dict[str, Any] = {
            "student_id": student_external,
            "analysis": analysis,
            "generated_task": generated,
        }
        await self._cache.set_json(pipeline_cache_key, body)
        await self._queue.complete_with_result(task_id, body)
        await deliver_webhook(webhook_url, body)


async def amain() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    ca = CodeAnalyzeModel()
    ca.ensure_loaded()
    gen = BrokenCodeGenModel()
    gen.ensure_loaded()
    w = PipelineWorker(ca, gen)
    await w.run_forever()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
