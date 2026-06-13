from __future__ import annotations

import logging
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request

from gateway.schemas.request import PipelineIn
from gateway.schemas.response import TaskAccepted
from gateway.services.auth import AuthContext, check_auth_rate_limit, ensure_student_access, verify_auth_context
from gateway.services.cache import CacheService, pipeline_cache_key
from gateway.services.queue import QueueService
from gateway.services.students import get_or_create_student

logger = logging.getLogger(__name__)

router = APIRouter()


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


def get_queue(request: Request) -> QueueService:
    return request.app.state.queue


def get_cache(request: Request) -> CacheService:
    return request.app.state.cache


@router.post("/pipeline", response_model=TaskAccepted)
async def pipeline(
    body: PipelineIn,
    ctx: AuthContext = Depends(verify_auth_context),
    r: redis.Redis = Depends(get_redis),
    queue: QueueService = Depends(get_queue),
    cache: CacheService = Depends(get_cache),
) -> TaskAccepted:
    await check_auth_rate_limit(r, ctx)
    ensure_student_access(ctx, body.student_id)
    student_uuid = await get_or_create_student(ctx.platform, str(body.student_id))
    ckey = pipeline_cache_key(body.task_description, body.code)
    cached = await cache.get_json(ckey)
    if cached is not None:
        task_id = str(uuid.uuid4())
        await queue.set_status(task_id, "pending", platform_id=str(ctx.platform.id), student_id=str(body.student_id))
        await queue.complete_with_result(task_id, cached)
        await queue.enqueue_webhook(str(body.webhook_url), cached, task_id=task_id)
        return TaskAccepted(task_id=task_id)

    payload = {
        "student_external_id": str(body.student_id),
        "student_uuid": str(student_uuid),
        "platform_id": str(ctx.platform.id),
        "task_description": body.task_description,
        "code": body.code,
        "webhook_url": str(body.webhook_url),
        "cache_key": ckey,
    }
    task_id = await queue.enqueue_pipeline(payload)
    return TaskAccepted(task_id=task_id)
