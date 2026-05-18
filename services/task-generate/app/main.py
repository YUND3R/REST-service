from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
import redis.asyncio as aioredis
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from edu_ml.auth_context import optional_uid, required_uid
from edu_ml.cors_util import parse_cors_origins
from edu_ml.job_redis import AsyncJobStore, JobRedisConfig, make_job_id
from edu_ml.redis_store import RedisStoreConfig, UserRedisStore
from edu_ml.schemas import AsyncJobStatusResponse, GenerateFromProgressRequest, GenerateFromProgressResponse, GenerateHealthResponse, GenerateTaskRequest, GenerateTaskResponse, QueuedJobAccepted, UserHistoryResponse, UserProfilePut, UserProgressPut, UserStoredEnvelope, coerce_ml_task
from edu_ml.settings_auth import get_auth_settings
from edu_ml.sqs_producer import send_message
from edu_ml.s3_training_archive import try_archive_generate_task_for_training
from edu_ml.tags_util import normalize_three_tags
from task_svc.generate_runtime import generate_broken_task, preload_model, runtime
from task_svc.settings_generate import get_generate_settings
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _job_status(job_id: str, doc: dict[str, Any] | None) -> AsyncJobStatusResponse:
    if not doc:
        return AsyncJobStatusResponse(job_id=job_id, status='unknown', result=None, error=None, created_at=None, updated_at=None)
    st_raw = doc.get('status', 'unknown')
    st = st_raw if st_raw in ('pending', 'processing', 'completed', 'failed', 'unknown') else 'unknown'
    return AsyncJobStatusResponse(job_id=job_id, status=st, result=doc.get('result'), error=doc.get('error'), created_at=doc.get('created_at'), updated_at=doc.get('updated_at'))

def _hint_lists_from_progress(d: dict[str, Any]) -> tuple[list[str] | None, list[str] | None, list[str] | None]:

    def pick(key: str) -> list[str] | None:
        v = d.get(key)
        if v is None or not isinstance(v, list):
            return None
        return [str(x) for x in v if x is not None]
    return (pick('tests_hints'), pick('requirements_hints'), pick('constraints_hints'))

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_generate_settings()
    app.state.user_store = None
    app.state.job_store = None
    app.state.job_redis = None
    if settings.redis_url:
        cfg = RedisStoreConfig(url=settings.redis_url, history_max=settings.user_history_max, ttl_seconds=settings.redis_ttl_seconds)
        store = UserRedisStore(cfg)
        try:
            await store.connect()
            app.state.user_store = store
            logger.info('Redis user storage connected for task-generate')
        except Exception as e:
            logger.warning('Redis unavailable, user storage disabled (%s)', type(e).__name__)
        try:
            job_r = aioredis.from_url(settings.redis_url, decode_responses=True)
            await job_r.ping()
            app.state.job_redis = job_r
            app.state.job_store = AsyncJobStore(JobRedisConfig(url=settings.redis_url, key_prefix='edu:job:generate:', ttl_seconds=settings.job_result_ttl_seconds), job_r)
            logger.info('Redis job store connected for SQS generate')
        except Exception as e:
            logger.warning('Redis job store unavailable (%s)', type(e).__name__)
    if settings.preload_model:
        logger.info('Preloading task-generate model...')
        await asyncio.to_thread(preload_model)
    yield
    store_obj = getattr(app.state, 'user_store', None)
    if isinstance(store_obj, UserRedisStore) and store_obj.connected:
        await store_obj.close()
    jr = getattr(app.state, 'job_redis', None)
    if jr is not None:
        await jr.close()
app = FastAPI(title='Task Generate Service', version='0.2.0', lifespan=lifespan)
_cors = get_generate_settings()
app.add_middleware(CORSMiddleware, allow_origins=parse_cors_origins(_cors.cors_origins), allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

@app.get('/health', response_model=GenerateHealthResponse)
def health(request: Request) -> GenerateHealthResponse:
    store = getattr(request.app.state, 'user_store', None)
    redis_ok = isinstance(store, UserRedisStore) and store.connected
    return GenerateHealthResponse(status='ok', model_loaded=runtime.model is not None, redis_connected=redis_ok, auth_enabled=get_auth_settings().auth_enabled)

@app.put('/v1/user/progress')
async def put_user_progress(req: UserProgressPut, request: Request, user_id: str=Depends(required_uid)) -> dict[str, Any]:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    try:
        return await store.set_user_progress(user_id, weak_tags=list(req.weak_tags), difficulty=req.difficulty, weights=req.weights, tests_hints=req.tests_hints, requirements_hints=req.requirements_hints, constraints_hints=req.constraints_hints)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

@app.get('/v1/user/progress', response_model=UserStoredEnvelope)
async def get_user_progress(request: Request, user_id: str=Depends(required_uid)) -> UserStoredEnvelope:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    data = await store.get_user_progress(user_id)
    return UserStoredEnvelope(found=data is not None, data=data)

@app.put('/v1/user/profile')
async def put_user_profile(req: UserProfilePut, request: Request, user_id: str=Depends(required_uid)) -> dict[str, Any]:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    patch = req.model_dump(exclude_unset=True)
    return await store.merge_user_profile(user_id, patch)

@app.get('/v1/user/profile', response_model=UserStoredEnvelope)
async def get_user_profile(request: Request, user_id: str=Depends(required_uid)) -> UserStoredEnvelope:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    data = await store.get_user_profile(user_id)
    return UserStoredEnvelope(found=data is not None, data=data)

@app.post('/v1/generate-from-progress', response_model=GenerateFromProgressResponse)
async def generate_from_progress(
    request: Request,
    user_id: Annotated[str, Depends(required_uid)],
    body: Annotated[GenerateFromProgressRequest, Body(default_factory=GenerateFromProgressRequest)],
) -> GenerateFromProgressResponse:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    progress = await store.get_user_progress(user_id)
    weakest = await store.get_weakest_tags(user_id, k=3)
    if weakest:
        try:
            t1, t2, t3 = normalize_three_tags(weakest)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f'Некорректные теги из статистики анализа: {e}') from e
    elif progress:
        try:
            t1, t2, t3 = normalize_three_tags([str(x) for x in progress.get('weak_tags') or []])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f'Некорректные weak_tags в прогрессе: {e}') from e
    else:
        raise HTTPException(status_code=404, detail='Нет статистики по анализам (нужен хотя бы один /v1/analyze с авторизацией) и нет сохранённого прогресса (PUT /v1/user/progress).')
    diff_raw = (progress.get('difficulty') if progress else None) or 'medium'
    difficulty_used: str = body.difficulty_override or diff_raw
    if difficulty_used not in ('easy', 'medium', 'hard'):
        difficulty_used = 'medium'
    wlist = progress.get('weights') if progress else None
    weights: tuple[float, float, float] | None
    if isinstance(wlist, list) and len(wlist) >= 3:
        weights = (float(wlist[0]), float(wlist[1]), float(wlist[2]))
    else:
        weights = None
    th, rh, ch = _hint_lists_from_progress(progress) if progress else (None, None, None)
    raw, task, ok = await asyncio.to_thread(generate_broken_task, tag1=t1, tag2=t2, tag3=t3, difficulty=difficulty_used, weights=weights, tests_hints=th, requirements_hints=rh, constraints_hints=ch)
    try:
        await store.save_task(user_id, task=task, raw_completion=raw, parse_ok=ok, tag1=t1, tag2=t2, tag3=t3, difficulty=difficulty_used)
    except Exception as e:
        logger.warning('Redis save_task failed (from-progress) (%s)', type(e).__name__)

    async def _s3_gen_fp() -> None:
        try:
            await asyncio.to_thread(try_archive_generate_task_for_training, user_id=user_id, task=task, raw_completion=raw, parse_ok=ok, tag1=t1, tag2=t2, tag3=t3, difficulty=difficulty_used, job_id=None)
        except Exception as e:
            logger.warning('S3 model-training export: %s', type(e).__name__)
    asyncio.create_task(_s3_gen_fp())
    d_final: Literal['easy', 'medium', 'hard']
    if difficulty_used in ('easy', 'medium', 'hard'):
        d_final = difficulty_used
    else:
        d_final = 'medium'
    return GenerateFromProgressResponse(task=task, task_typed=coerce_ml_task(task), raw_completion=raw, parse_ok=ok, used_weak_tags=(t1, t2, t3), difficulty_used=d_final)

@app.post('/v1/generate-task', response_model=GenerateTaskResponse)
async def generate_task(req: GenerateTaskRequest, request: Request, user_id: str | None=Depends(optional_uid)) -> GenerateTaskResponse:
    raw, task, ok = await asyncio.to_thread(generate_broken_task, tag1=req.tag1, tag2=req.tag2, tag3=req.tag3, difficulty=req.difficulty, weights=req.weights, tests_hints=req.tests_hints, requirements_hints=req.requirements_hints, constraints_hints=req.constraints_hints)
    store = getattr(request.app.state, 'user_store', None)
    if user_id and isinstance(store, UserRedisStore) and store.connected:
        try:
            await store.save_task(user_id, task=task, raw_completion=raw, parse_ok=ok, tag1=req.tag1, tag2=req.tag2, tag3=req.tag3, difficulty=req.difficulty)
        except Exception as e:
            logger.warning('Redis save_task failed (%s)', type(e).__name__)

    async def _s3_gen() -> None:
        try:
            await asyncio.to_thread(try_archive_generate_task_for_training, user_id=user_id, task=task, raw_completion=raw, parse_ok=ok, tag1=req.tag1, tag2=req.tag2, tag3=req.tag3, difficulty=req.difficulty, job_id=None)
        except Exception as e:
            logger.warning('S3 model-training export: %s', type(e).__name__)
    asyncio.create_task(_s3_gen())
    return GenerateTaskResponse(task=task, task_typed=coerce_ml_task(task), raw_completion=raw, parse_ok=ok)

@app.post('/v1/queue/generate-task', response_model=QueuedJobAccepted)
async def queue_generate_task(req: GenerateTaskRequest, request: Request, user_id: str | None=Depends(optional_uid)) -> QueuedJobAccepted:
    settings = get_generate_settings()
    if not settings.sqs_generate_queue_url:
        raise HTTPException(status_code=503, detail='Не задан SQS_GENERATE_QUEUE_URL')
    job_store = getattr(request.app.state, 'job_store', None)
    if not isinstance(job_store, AsyncJobStore):
        raise HTTPException(status_code=503, detail='Redis недоступен для очереди заданий')
    job_id = make_job_id()
    await job_store.create_pending(job_id)
    body: dict[str, Any] = {'job_id': job_id, 'payload': req.model_dump()}
    if user_id:
        body['user_id'] = user_id
    try:
        send_message(queue_url=settings.sqs_generate_queue_url, body=body, region=settings.aws_region)
    except Exception as e:
        logger.exception('SQS enqueue failed')
        raise HTTPException(status_code=502, detail=f'SQS: {e}') from e
    return QueuedJobAccepted(job_id=job_id)

@app.get('/v1/queue/generate-task/{job_id}', response_model=AsyncJobStatusResponse)
async def get_generate_queue_job(job_id: str, request: Request) -> AsyncJobStatusResponse:
    job_store = getattr(request.app.state, 'job_store', None)
    if not isinstance(job_store, AsyncJobStore):
        raise HTTPException(status_code=503, detail='Redis недоступен')
    doc = await job_store.get_doc(job_id)
    return _job_status(job_id, doc)

@app.get('/v1/user/last-task', response_model=UserStoredEnvelope)
async def user_last_task(request: Request, user_id: str=Depends(required_uid)) -> UserStoredEnvelope:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    data = await store.get_last_task(user_id)
    return UserStoredEnvelope(found=data is not None, data=data)

@app.get('/v1/user/task-history', response_model=UserHistoryResponse)
async def user_task_history(request: Request, user_id: str=Depends(required_uid), limit: int=Query(500, ge=1, le=10000), offset: int=Query(0, ge=0, le=1000000)) -> UserHistoryResponse:
    store = getattr(request.app.state, 'user_store', None)
    if not isinstance(store, UserRedisStore) or not store.connected:
        raise HTTPException(status_code=503, detail='Хранилище Redis не подключено (задайте REDIS_URL)')
    items, total = await store.get_task_history(user_id, limit=limit, offset=offset)
    return UserHistoryResponse(items=items, count=len(items), total=total)
