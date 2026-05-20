from __future__ import annotations

import os
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.config import get_settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _postgres_ssl_connect_args() -> dict[str, ssl.SSLContext]:
    ca_file = os.getenv("POSTGRES_SSL_CA_FILE")
    cert_file = os.getenv("POSTGRES_SSL_CERT_FILE")
    key_file = os.getenv("POSTGRES_SSL_KEY_FILE")
    if not ca_file and not cert_file and not key_file:
        return {}

    ctx = ssl.create_default_context(cafile=ca_file)
    ctx.check_hostname = os.getenv("POSTGRES_SSL_CHECK_HOSTNAME", "true").lower() in {"1", "true", "yes", "on"}
    if cert_file and key_file:
        ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return {"ssl": ctx}


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            connect_args=_postgres_ssl_connect_args(),
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def ping_database() -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
