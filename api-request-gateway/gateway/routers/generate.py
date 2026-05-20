from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request

from db.models import GeneratedTask, Platform
from db.session import get_session_factory
from gateway.schemas.request import GenerateIn
from gateway.schemas.response import TaskAccepted
from gateway.services.auth import check_rate_limit, verify_api_key
from gateway.services.cache import CacheService, generate_cache_key
from gateway.services.queue import QueueService
from gateway.services.students import get_or_create_student
from gateway.services.webhook import deliver_webhook

logger = logging.getLogger(__name__)

router = APIRouter()


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


def get_queue(request: Request) -> QueueService:
    return request.app.state.queue


def get_cache(request: Request) -> CacheService:
    return request.app.state.cache


async def _persist_generated(
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


@router.post("/generate", response_model=TaskAccepted)
async def generate(
    body: GenerateIn,
    platform: Platform = Depends(verify_api_key),
    r: redis.Redis = Depends(get_redis),
    queue: QueueService = Depends(get_queue),
    cache: CacheService = Depends(get_cache),
) -> TaskAccepted:
    await check_rate_limit(r, platform.api_key)
    student_uuid = await get_or_create_student(platform, body.student_id)
    ckey = generate_cache_key(list(body.tags), body.difficulty)
    cached = await cache.get_json(ckey)

    if cached is not None:
        task_id = str(uuid.uuid4())
        await queue.set_status(task_id, "pending")
        webhook_body: dict[str, Any] = {"student_id": body.student_id, "generated_task": cached}
        await queue.complete_with_result(task_id, webhook_body)
        asyncio.create_task(deliver_webhook(str(body.webhook_url), webhook_body))
        asyncio.create_task(
            _persist_generated(student_uuid, list(body.tags), body.difficulty, cached, None)
        )
        return TaskAccepted(task_id=task_id)

    payload = {
        "student_external_id": body.student_id,
        "student_uuid": str(student_uuid),
        "platform_id": str(platform.id),
        "tags": list(body.tags),
        "difficulty": body.difficulty,
        "webhook_url": str(body.webhook_url),
        "cache_key": ckey,
    }
    task_id = await queue.enqueue_generate(payload)
    return TaskAccepted(task_id=task_id)
