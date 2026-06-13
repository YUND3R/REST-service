from __future__ import annotations

from contextlib import asynccontextmanager

from gateway.config import get_settings
from gateway.main import create_app
from starlette.testclient import TestClient


class _DummyRedis:
    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


def _build_test_app(monkeypatch):
    @asynccontextmanager
    async def test_lifespan(app):
        app.state.redis = _DummyRedis()
        yield

    monkeypatch.setattr("gateway.main.lifespan", test_lifespan)
    get_settings.cache_clear()
    return create_app()


def test_docs_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DOCS_ENABLED", raising=False)
    app = _build_test_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/docs")
        assert resp.status_code == 200


def test_docs_disabled_when_env_false(monkeypatch):
    monkeypatch.setenv("DOCS_ENABLED", "false")
    app = _build_test_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/docs")
        assert resp.status_code == 404


def test_openapi_available_and_contains_core_paths(monkeypatch):
    monkeypatch.setenv("DOCS_ENABLED", "true")
    app = _build_test_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        paths = spec.get("paths", {})
        assert "/api/v1/analyze" in paths
        assert "/api/v1/generate" in paths
        assert "/api/v1/status/{task_id}" in paths
