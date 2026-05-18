from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.auth_router import router as auth_router
from edu_ml.cors_util import parse_cors_origins
app = FastAPI(title='Auth Service', version='0.1.0')
app.add_middleware(CORSMiddleware, allow_origins=parse_cors_origins('*'), allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(auth_router)

@app.get('/health')
def health() -> dict[str, str]:
    return {'status': 'ok', 'service': 'auth-service'}
