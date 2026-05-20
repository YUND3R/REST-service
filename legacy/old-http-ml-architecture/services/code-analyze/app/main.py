from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from analyze_svc.analyze_runtime import analyze_code, preload_model, runtime
from analyze_svc.settings_analyze import get_analyze_settings
from edu_ml.auth_context import optional_uid, required_uid
from edu_ml.cors_util import parse_cors_origins
from edu_ml.job_redis import AsyncJobStore, JobRedisConfig, make_job_id
from edu_ml.redis_store import RedisStoreConfig, UserRedisStore
from edu_ml.s3_training_archive import try_archive_analyze_for_training
from edu_ml.schemas import (
    AnalyzeHealthResponse,
    AnalyzeRequest,
    AnalyzeResponse,
    AsyncJobStatusResponse,
    QueuedJobAccepted,
    UserHistoryResponse,
    UserStoredEnvelope,
    analyze_request_storage_blob,
)
from edu_ml.settings_auth import get_auth_settings
from edu_ml.sqs_producer import send_message
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _job_status(job_id: str, doc: dict[str, Any] | None) -> AsyncJobStatusResponse:
    if not doc:
        return AsyncJobStatusResponse(
            job_id=job_id, status="unknown", result=None, error=None, created_at=None, updated_at=None
        )
    st_raw = doc.get("status", "unknown")
    st = st_raw if st_raw in ("pending", "processing", "completed", "failed", "unknown") else "unknown"
    return AsyncJobStatusResponse(
        job_id=job_id,
        status=st,
        result=doc.get("result"),
        error=doc.get("error"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_analyze_settings()
    app.state.user_store = None
    app.state.job_store = None
    app.state.job_redis = None
    if settings.redis_url:
        cfg = RedisStoreConfig(
            url=settings.redis_url, history_max=settings.user_history_max, ttl_seconds=settings.redis_ttl_seconds
        )
        store = UserRedisStore(cfg)
        try:
            await store.connect()
            app.state.user_store = store
            logger.info("Redis user storage connected for code-analyze")
        except Exception as e:
            logger.warning("Redis unavailable, user storage disabled (%s)", type(e).__name__)
        try:
            job_r = aioredis.from_url(settings.redis_url, decode_responses=True)
            await job_r.ping()
            app.state.job_redis = job_r
            app.state.job_store = AsyncJobStore(
                JobRedisConfig(
                    url=settings.redis_url, key_prefix="edu:job:analyze:", ttl_seconds=settings.job_result_ttl_seconds
                ),
                job_r,
            )
            logger.info("Redis job store connected for SQS analyze")
        except Exception as e:
            logger.warning("Redis job store unavailable (%s)", type(e).__name__)
    if settings.preload_model:
        logger.info("Preloading code-analyze model...")
        await asyncio.to_thread(preload_model)
    yield
    store_obj = getattr(app.state, "user_store", None)
    if isinstance(store_obj, UserRedisStore) and store_obj.connected:
        await store_obj.close()
    jr = getattr(app.state, "job_redis", None)
    if jr is not None:
        await jr.close()


app = FastAPI(title="Code Analyze Service", version="0.1.0", lifespan=lifespan)
_cors = get_analyze_settings()
_origins = parse_cors_origins(_cors.cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=AnalyzeHealthResponse)
def health(request: Request) -> AnalyzeHealthResponse:
    store = getattr(request.app.state, "user_store", None)
    redis_ok = isinstance(store, UserRedisStore) and store.connected
    return AnalyzeHealthResponse(
        status="ok",
        model_loaded=runtime.model is not None,
        redis_connected=redis_ok,
        auth_enabled=get_auth_settings().auth_enabled,
    )


@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze(
    req: AnalyzeRequest, request: Request, user_id: str | None = Depends(optional_uid)
) -> AnalyzeResponse:
    result = await asyncio.to_thread(analyze_code, code=req.code, task=req.task, task_context=req.task_context)
    text = result.analysis
    scores = result.tag_scores if result.tag_scores else None
    store = getattr(request.app.state, "user_store", None)
    if user_id and isinstance(store, UserRedisStore) and store.connected:
        try:
            await store.save_analyze(
                user_id,
                analysis=text,
                code=req.code,
                task_context=analyze_request_storage_blob(req),
                task=req.task.model_dump() if req.task else None,
                tag_scores=scores,
                report_json=result.report_json,
            )
        except Exception as e:
            logger.warning("Redis save_analyze failed (%s)", type(e).__name__)

    async def _s3_training_export() -> None:
        try:
            tdict = req.task.model_dump(mode="json") if req.task is not None else None
            await asyncio.to_thread(
                try_archive_analyze_for_training,
                user_id=user_id,
                code=req.code,
                task=tdict,
                task_context=req.task_context,
                analysis=text,
                tag_scores=scores,
                report_json=result.report_json,
                raw_model_completion=result.raw_completion,
                job_id=None,
            )
        except Exception as e:
            logger.warning("S3 model-training export: %s", type(e).__name__)

    asyncio.create_task(_s3_training_export())
    return AnalyzeResponse(analysis=text, tag_scores=scores, report=result.report_json)


@app.post("/v1/queue/analyze", response_model=QueuedJobAccepted)
async def queue_analyze(
    req: AnalyzeRequest, request: Request, user_id: str | None = Depends(optional_uid)
) -> QueuedJobAccepted:
    settings = get_analyze_settings()
    if not settings.sqs_analyze_queue_url:
        raise HTTPException(status_code=503, detail="Не задан SQS_ANALYZE_QUEUE_URL")
    job_store = getattr(request.app.state, "job_store", None)
    if not isinstance(job_store, AsyncJobStore):
        raise HTTPException(status_code=503, detail="Redis недоступен для очереди заданий")
    job_id = make_job_id()
    await job_store.create_pending(job_id)
    body: dict[str, Any] = {"job_id": job_id, "code": req.code}
    if req.task is not None:
        body["task"] = req.task.model_dump()
    if req.task_context:
        body["task_context"] = req.task_context
    if user_id:
        body["user_id"] = user_id
    try:
        send_message(queue_url=settings.sqs_analyze_queue_url, body=body, region=settings.aws_region)
    except Exception as e:
        logger.exception("SQS enqueue failed")
        raise HTTPException(status_code=502, detail=f"SQS: {e}") from e
    return QueuedJobAccepted(job_id=job_id)


@app.get("/v1/queue/analyze/{job_id}", response_model=AsyncJobStatusResponse)
async def get_analyze_queue_job(job_id: str, request: Request) -> AsyncJobStatusResponse:
    job_store = getattr(request.app.state, "job_store", None)
    if not isinstance(job_store, AsyncJobStore):
        raise HTTPException(status_code=503, detail="Redis недоступен")
    doc = await job_store.get_doc(job_id)
    return _job_status(job_id, doc)


@app.get("/v1/user/last-analyze", response_model=UserStoredEnvelope)
async def user_last_analyze(request: Request, user_id: str = Depends(required_uid)) -> UserStoredEnvelope:
    store = getattr(request.app.state, "user_store", None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail="Хранилище Redis не подключено (задайте REDIS_URL)")
    data = await store.get_last_analyze(user_id)
    return UserStoredEnvelope(found=data is not None, data=data)


@app.get("/v1/user/analyze-history", response_model=UserHistoryResponse)
async def user_analyze_history(
    request: Request,
    user_id: str = Depends(required_uid),
    limit: int = Query(500, ge=1, le=10000),
    offset: int = Query(0, ge=0, le=1000000),
) -> UserHistoryResponse:
    store = getattr(request.app.state, "user_store", None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail="Хранилище Redis не подключено (задайте REDIS_URL)")
    items, total = await store.get_analyze_history(user_id, limit=limit, offset=offset)
    return UserHistoryResponse(items=items, count=len(items), total=total)
