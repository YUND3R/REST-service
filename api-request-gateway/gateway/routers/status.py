from __future__ import annotations

import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request

from db.models import Platform
from gateway.schemas.response import TaskStatusResponse
from gateway.services.auth import check_rate_limit, verify_api_key
from gateway.services.queue import STATUS_DONE, STATUS_FAILED, STATUS_PENDING, STATUS_PROCESSING, QueueService

router = APIRouter()


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


def get_queue(request: Request) -> QueueService:
    return request.app.state.queue


def _normalize_status(raw: str | None) -> str:
    if raw in (STATUS_PENDING, STATUS_PROCESSING, STATUS_DONE, STATUS_FAILED):
        return raw
    return STATUS_PENDING


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def task_status(
    task_id: uuid.UUID,
    platform: Platform = Depends(verify_api_key),
    r: redis.Redis = Depends(get_redis),
    queue: QueueService = Depends(get_queue),
) -> TaskStatusResponse:
    await check_rate_limit(r, platform.api_key)
    task_id_str = str(task_id)
    snap = await queue.get_snapshot(task_id_str)
    if not snap:
        raise HTTPException(status_code=404, detail="Unknown task_id")
    if str(snap.get("platform_id") or "") != str(platform.id):
        raise HTTPException(status_code=404, detail="Unknown task_id")
    raw = snap.get("status")
    st = _normalize_status(str(raw) if raw is not None else None)
    err = snap.get("error")
    res = snap.get("result") if st == STATUS_DONE else None
    return TaskStatusResponse(task_id=task_id_str, status=st, error=err, result=res)
