from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

from gateway.config import get_settings
from gateway.services.cache import analyze_cache_key, generate_cache_key
from gateway.services.queue import STATUS_FAILED, STATUS_PROCESSING, QueueService
from gateway.services.student_profile import merge_analysis_into_student_profile
from models.code_analyze import score_to_difficulty
from workers.analyze_worker import persist_analysis
from workers.generate_worker import persist_generated
from workers.pipeline_worker import persist_pipeline

logger = logging.getLogger(__name__)


def mock_analysis(code: str) -> dict[str, Any]:
    tags = ["python", "logic"]
    if "for " in code or "while " in code:
        tags.append("loops")
    if "def " in code:
        tags.append("functions")
    return {
        "score": 7,
        "weak_spots": [
            {
                "line": None,
                "issue": "CPU test mode: real model inference is disabled",
                "hint": "This response verifies queue, API, Redis and PostgreSQL integration.",
            }
        ],
        "tags": tags,
        "recommendations": ["Run the same request with GPU workers for real model output."],
    }


def mock_generated_task(tags: list[str], difficulty: str) -> dict[str, Any]:
    primary = tags[0] if tags else "python"
    return {
        "title": f"CPU test task for {primary}",
        "difficulty": difficulty,
        "topic_tags": {tag: 1 for tag in tags},
        "task_context": "Find and fix the intentional bug in the function.",
        "tests": [
            {"input": "add_one(1)", "expected": 2},
            {"input": "add_one(5)", "expected": 6},
        ],
        "broken_code": "def add_one(value):\n    return value - 1\n",
    }


class CpuMockWorkers:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
        self._queue = QueueService(self._redis)
        self._consumer = os.environ.get("CONSUMER_NAME", socket.gethostname())

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(
        self,
        stream: str,
        group: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self.ensure_group(stream, group)
        while True:
            resp = await self._redis.xreadgroup(
                group,
                self._consumer,
                {stream: ">"},
                count=int(os.environ.get("STREAM_BATCH", "4")),
                block=5000,
            )
            if not resp:
                continue
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    job: dict[str, Any] = {}
                    try:
                        job = json.loads(fields.get("data") or "{}")
                        await handler(job)
                        await self._redis.xack(stream, group, msg_id)
                    except Exception as e:
                        logger.exception("CPU mock job failed: %s", e)
                        if job.get("task_id"):
                            await self._queue.set_status(str(job["task_id"]), STATUS_FAILED, error=str(e))
                        await self._redis.xack(stream, group, msg_id)

    async def handle_analyze(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(str(job["student_uuid"]))
        task_description = str(job["task_description"])
        code = str(job["code"])
        webhook_url = str(job["webhook_url"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)
        analysis = mock_analysis(code)
        await persist_analysis(student_uuid, task_description, code, analysis)

        body = {"student_id": student_external, "analysis": analysis}
        await self._queue.complete_with_result(task_id, body)
        await self._queue.enqueue_webhook(webhook_url, body, task_id=task_id)

    async def handle_generate(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(str(job["student_uuid"]))
        tags = list(job.get("tags") or ["python"])
        difficulty = str(job.get("difficulty") or "medium")
        webhook_url = str(job["webhook_url"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)
        generated = mock_generated_task(tags, difficulty)
        await persist_generated(student_uuid, tags, difficulty, generated, None)

        body = {"student_id": student_external, "generated_task": generated}
        await self._queue.complete_with_result(task_id, body)
        await self._queue.enqueue_webhook(webhook_url, body, task_id=task_id)

    async def handle_pipeline(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(str(job["student_uuid"]))
        task_description = str(job["task_description"])
        code = str(job["code"])
        webhook_url = str(job["webhook_url"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)
        analysis = mock_analysis(code)
        difficulty = score_to_difficulty(int(analysis["score"]))
        profile_tags = await merge_analysis_into_student_profile(
            self._redis,
            student_id=str(student_uuid),
            analysis=analysis,
            ttl_seconds=self._settings.cache_ttl_seconds,
        )
        tags = profile_tags or list(analysis.get("tags") or ["python"])
        generated = mock_generated_task(tags, difficulty)
        await persist_pipeline(student_uuid, task_description, code, analysis, generated, difficulty, tags)

        body = {
            "student_id": student_external,
            "analysis": analysis,
            "generated_task": generated,
            "profile_tags_used": tags,
        }
        await self._queue.complete_with_result(task_id, body)
        await self._queue.enqueue_webhook(webhook_url, body, task_id=task_id)

        await self._redis.set(
            analyze_cache_key(task_description, code),
            json.dumps(analysis, ensure_ascii=False),
            ex=self._settings.cache_ttl_seconds,
        )
        await self._redis.set(
            generate_cache_key(tags, difficulty),
            json.dumps(generated, ensure_ascii=False),
            ex=self._settings.cache_ttl_seconds,
        )

    async def run(self) -> None:
        await asyncio.gather(
            self.consume(self._settings.stream_analyze, "analyze_workers", self.handle_analyze),
            self.consume(self._settings.stream_generate, "generate_workers", self.handle_generate),
            self.consume(self._settings.stream_pipeline, "pipeline_workers", self.handle_pipeline),
        )


async def amain() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logger.info("CPU mock workers started: analyze, generate and pipeline queues are active")
    await CpuMockWorkers().run()


if __name__ == "__main__":
    asyncio.run(amain())
