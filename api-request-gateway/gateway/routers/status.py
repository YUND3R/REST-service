from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from db.models import Platform
from gateway.schemas.response import TaskStatusResponse
from gateway.services.auth import verify_api_key
from gateway.services.queue import STATUS_DONE, STATUS_FAILED, STATUS_PENDING, STATUS_PROCESSING, QueueService

router = APIRouter()


def get_queue(request: Request) -> QueueService:
    return request.app.state.queue


def _normalize_status(raw: str | None) -> str:
    if raw in (STATUS_PENDING, STATUS_PROCESSING, STATUS_DONE, STATUS_FAILED):
        return raw
    return STATUS_PENDING


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def task_status(
    task_id: str,
    _: Platform = Depends(verify_api_key),
    queue: QueueService = Depends(get_queue),
) -> TaskStatusResponse:
    snap = await queue.get_snapshot(task_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Unknown task_id")
    raw = snap.get("status")
    st = _normalize_status(str(raw) if raw is not None else None)
    err = snap.get("error")
    res = snap.get("result") if st == STATUS_DONE else None
    return TaskStatusResponse(task_id=task_id, status=st, error=err, result=res)
