from __future__ import annotations

import os

from edu_ml.cors_util import parse_cors_origins
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth_router import router as auth_router

app = FastAPI(title="Auth Service", version="0.1.0")
_origins = parse_cors_origins(os.getenv("CORS_ORIGINS", "https://app.example.com"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "auth-service"}
