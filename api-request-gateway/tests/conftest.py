from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
import redis.asyncio as redis
from starlette.testclient import TestClient

from db.models import Platform
from gateway.main import create_app
from gateway.services.auth import api_key_hash, verify_api_key
from gateway.services.cache import CacheService
from gateway.services.queue import QueueService

TEST_API_KEY = "test-integration-key"


class FakeRedis:
    """Minimal async Redis double for queue/status integration tests."""

    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.groups: set[tuple[str, str]] = set()
        self._stream_seq = 0

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value

    async def expire(self, key: str, ttl: int) -> None:
        return None

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self._stream_seq += 1
        entry_id = f"{self._stream_seq}-0"
        self.streams.setdefault(stream, []).append((entry_id, fields))
        return entry_id

    async def xgroup_create(
        self,
        stream: str,
        group: str,
        id: str = "0-0",
        mkstream: bool = False,
    ) -> None:
        key = (stream, group)
        if key in self.groups:
            raise redis.ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)
        if mkstream:
            self.streams.setdefault(stream, [])


class FakePipeline:
    def __init__(self, backend: FakeRedis) -> None:
        self._backend = backend
        self._ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> FakePipeline:
        self._ops.append(("incr", key))
        return self

    def ttl(self, key: str) -> FakePipeline:
        self._ops.append(("ttl", key))
        return self

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for op, key in self._ops:
            if op == "incr":
                current = int(self._backend.strings.get(key, "0"))
                current += 1
                self._backend.strings[key] = str(current)
                results.append(current)
            elif op == "ttl":
                results.append(-1)
        self._ops = []
        return results


@pytest.fixture
def test_platform() -> Platform:
    return Platform(
        id=uuid.uuid4(),
        name="integration-test",
        api_key=api_key_hash(TEST_API_KEY),
        webhook_url=None,
    )


@pytest.fixture
def gateway_app(monkeypatch: pytest.MonkeyPatch):
    fake_redis = FakeRedis()

    @asynccontextmanager
    async def test_lifespan(app):
        app.state.redis = fake_redis
        app.state.queue = QueueService(fake_redis)
        app.state.cache = CacheService(fake_redis)
        yield

    async def fake_student(_platform: Platform, external_student_id: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_DNS, external_student_id)

    monkeypatch.setattr("gateway.main.lifespan", test_lifespan)
    monkeypatch.setattr("gateway.routers.analyze.get_or_create_student", fake_student)

    app = create_app()
    with TestClient(app) as client:
        yield client, app.state.queue, app

    app.dependency_overrides.clear()


@pytest.fixture
def gateway_client(gateway_app, test_platform: Platform):
    client, queue, app = gateway_app

    async def override_api_key() -> Platform:
        return test_platform

    app.dependency_overrides[verify_api_key] = override_api_key
    yield client, queue, test_platform
    app.dependency_overrides.pop(verify_api_key, None)
