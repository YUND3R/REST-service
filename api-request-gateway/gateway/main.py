from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db.session import get_engine, ping_database
from gateway.config import get_settings
from gateway.routers import analyze, generate, pipeline, status
from gateway.services.cache import CacheService
from gateway.services.queue import QueueService

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)


def _parse_cors_origins(raw: str) -> list[str]:
    raw = raw.strip()
    if raw == "*":
        return ["*"]
    return [x.strip() for x in raw.split(",") if x.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    r = redis.from_url(settings.redis_url, decode_responses=True)
    await r.ping()
    app.state.redis = r
    app.state.queue = QueueService(r)
    app.state.cache = CacheService(r)
    logger.info("Redis connected")
    get_engine()
    logger.info("DB engine initialized")
    yield
    await r.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    origins = _parse_cors_origins(settings.cors_origins)
    allow_creds = "*" not in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_creds,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/health"):
            logger.info("%s %s", request.method, path)
        return await call_next(request)

    app.include_router(analyze.router, prefix="/api/v1")
    app.include_router(generate.router, prefix="/api/v1")
    app.include_router(pipeline.router, prefix="/api/v1")
    app.include_router(status.router, prefix="/api/v1")

    @app.get("/health")
    async def health_root():
        return {"status": "ok", "version": settings.app_version}

    @app.get("/health/live")
    async def health_live():
        return {"status": "ok", "version": settings.app_version}

    @app.get("/health/ready")
    async def health_ready(request: Request):
        redis_ok = False
        try:
            await request.app.state.redis.ping()
            redis_ok = True
        except Exception:
            logger.exception("Redis readiness check failed")

        db_ok = await ping_database()
        if redis_ok and db_ok:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "ready",
                    "redis": True,
                    "database": True,
                    "version": settings.app_version,
                    "environment": settings.environment,
                },
            )
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "redis": redis_ok,
                "database": db_ok,
            },
        )

    return app


app = create_app()
