from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from edu_ml.tag_report import extract_tag_mastery_from_report
from edu_ml.tag_stats import clamp_tag_score, mean_from_blob, merge_tag_sample_blob
from edu_ml.tags_util import normalize_three_tags

logger = logging.getLogger(__name__)


@dataclass
class RedisStoreConfig:
    url: str
    history_max: int = 0
    history_fetch_cap: int = 10000
    ttl_seconds: int | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class UserRedisStore:
    def __init__(self, config: RedisStoreConfig):
        self._config = config
        self._client: aioredis.Redis | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        self._client = aioredis.from_url(self._config.url, decode_responses=True)
        await self._client.ping()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    def _k_hist_analyze(self, user_id: str) -> str:
        return f"edu:user:{user_id}:analyze:history"

    def _k_hist_task(self, user_id: str) -> str:
        return f"edu:user:{user_id}:task:history"

    def _k_progress(self, user_id: str) -> str:
        return f"edu:user:{user_id}:progress"

    def _k_profile(self, user_id: str) -> str:
        return f"edu:user:{user_id}:profile"

    def _k_tag_stats(self, user_id: str) -> str:
        return f"edu:user:{user_id}:tag_stats"

    async def _maybe_ttl(self, *keys: str) -> None:
        if not self._client or not self._config.ttl_seconds:
            return
        ttl = int(self._config.ttl_seconds)
        for k in keys:
            await self._client.expire(k, ttl)

    async def save_analyze(
        self,
        user_id: str,
        *,
        analysis: str,
        code: str,
        task_context: str,
        task: dict[str, Any] | None = None,
        tag_scores: dict[str, float] | None = None,
        report_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert self._client is not None
        payload: dict[str, Any] = {
            "analysis": analysis,
            "code": code,
            "task_context": task_context,
            "stored_at": _now_iso(),
        }
        if task is not None:
            payload["task"] = task
        if report_json is not None:
            payload["report"] = report_json
        if tag_scores:
            ts: dict[str, float] = {}
            for kk, vv in tag_scores.items():
                sk = str(kk).strip()
                if not sk:
                    continue
                m = clamp_tag_score(vv)
                if m is not None:
                    ts[sk] = m
            payload["tag_scores"] = ts
        elif report_json:
            tr = extract_tag_mastery_from_report(report_json)
            if tr:
                payload["tag_scores"] = tr
        raw = json.dumps(payload, ensure_ascii=False)
        k_hist = self._k_hist_analyze(user_id)
        await self._client.lpush(k_hist, raw)
        if self._config.history_max > 0:
            await self._client.ltrim(k_hist, 0, self._config.history_max - 1)
        await self._maybe_ttl(k_hist)
        ts_for_merge = payload.get("tag_scores") if isinstance(payload.get("tag_scores"), dict) else None
        if ts_for_merge:
            await self.merge_tag_mastery_observations(user_id, ts_for_merge)
            await self._record_tags_in_profile(user_id, list(ts_for_merge.keys()))
        return payload

    async def merge_tag_mastery_observations(self, user_id: str, mastery: dict[str, float]) -> None:
        assert self._client is not None
        if not mastery:
            return
        k = self._k_tag_stats(user_id)
        for tag, val in mastery.items():
            t = str(tag).strip()
            if not t:
                continue
            m = clamp_tag_score(val)
            if m is None:
                continue
            prev = await self._client.hget(k, t)
            blob = merge_tag_sample_blob(prev, m)
            await self._client.hset(k, t, blob)
        await self._maybe_ttl(k)

    async def get_weakest_tags(self, user_id: str, *, k: int = 3) -> list[str]:
        assert self._client is not None
        key = self._k_tag_stats(user_id)
        h = await self._client.hgetall(key)
        scored: list[tuple[str, float]] = []
        for tag, raw in h.items():
            mu = mean_from_blob(raw)
            if mu is not None:
                scored.append((tag, mu))
        scored.sort(key=lambda x: x[1])
        return [t for t, _ in scored[: max(0, k)]]

    async def get_last_analyze(self, user_id: str) -> dict[str, Any] | None:
        assert self._client is not None
        rows = await self._client.lrange(self._k_hist_analyze(user_id), 0, 0)
        if not rows:
            return None
        try:
            return json.loads(rows[0])
        except json.JSONDecodeError:
            return None

    async def get_analyze_history(
        self, user_id: str, *, limit: int, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        assert self._client is not None
        k_hist = self._k_hist_analyze(user_id)
        total = int(await self._client.llen(k_hist))
        if offset < 0:
            offset = 0
        cap = max(1, min(limit, self._config.history_fetch_cap))
        if offset >= total:
            return ([], total)
        n = min(cap, total - offset)
        rows = await self._client.lrange(k_hist, offset, offset + n - 1)
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r))
            except json.JSONDecodeError:
                continue
        return (out, total)

    async def save_task(
        self,
        user_id: str,
        *,
        task: dict[str, Any] | None,
        raw_completion: str,
        parse_ok: bool,
        tag1: str,
        tag2: str,
        tag3: str,
        difficulty: str,
    ) -> dict[str, Any]:
        assert self._client is not None
        payload = {
            "task": task,
            "raw_completion": raw_completion,
            "parse_ok": parse_ok,
            "request": {"tag1": tag1, "tag2": tag2, "tag3": tag3, "difficulty": difficulty},
            "stored_at": _now_iso(),
        }
        raw = json.dumps(payload, ensure_ascii=False)
        k_hist = self._k_hist_task(user_id)
        await self._client.lpush(k_hist, raw)
        if self._config.history_max > 0:
            await self._client.ltrim(k_hist, 0, self._config.history_max - 1)
        await self._maybe_ttl(k_hist)
        await self._record_tags_in_profile(user_id, [tag1, tag2, tag3])
        return payload

    async def get_last_task(self, user_id: str) -> dict[str, Any] | None:
        assert self._client is not None
        rows = await self._client.lrange(self._k_hist_task(user_id), 0, 0)
        if not rows:
            return None
        try:
            return json.loads(rows[0])
        except json.JSONDecodeError:
            return None

    async def get_task_history(self, user_id: str, *, limit: int, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        assert self._client is not None
        k_hist = self._k_hist_task(user_id)
        total = int(await self._client.llen(k_hist))
        if offset < 0:
            offset = 0
        cap = max(1, min(limit, self._config.history_fetch_cap))
        if offset >= total:
            return ([], total)
        n = min(cap, total - offset)
        rows = await self._client.lrange(k_hist, offset, offset + n - 1)
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r))
            except json.JSONDecodeError:
                continue
        return (out, total)

    async def _record_tags_in_profile(self, user_id: str, tags: list[str]) -> None:
        assert self._client is not None
        clean = [str(t).strip() for t in tags if str(t).strip()]
        if not clean:
            return
        k = self._k_profile(user_id)
        raw = await self._client.get(k)
        doc: dict[str, Any] = json.loads(raw) if raw else {}
        prev = doc.get("all_tags_used")
        if not isinstance(prev, list):
            prev = []
        merged = list(dict.fromkeys([str(x).strip() for x in prev if str(x).strip()] + clean))
        doc["all_tags_used"] = merged
        doc["updated_at"] = _now_iso()
        await self._client.set(k, json.dumps(doc, ensure_ascii=False))
        await self._maybe_ttl(k)

    async def _sync_profile_weak_and_tags_used(self, user_id: str, weak: list[str]) -> None:
        assert self._client is not None
        k = self._k_profile(user_id)
        raw = await self._client.get(k)
        doc: dict[str, Any] = json.loads(raw) if raw else {}
        doc["weak_tags"] = list(weak)
        self._merge_tags_into_doc(doc, weak)
        doc["updated_at"] = _now_iso()
        await self._client.set(k, json.dumps(doc, ensure_ascii=False))
        await self._maybe_ttl(k)

    @staticmethod
    def _merge_tags_into_doc(doc: dict[str, Any], extra: list[str]) -> None:
        prev = doc.get("all_tags_used")
        if not isinstance(prev, list):
            prev = []
        clean_prev = [str(x).strip() for x in prev if str(x).strip()]
        adding = [str(t).strip() for t in extra if str(t).strip()]
        doc["all_tags_used"] = list(dict.fromkeys(clean_prev + adding))

    async def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        assert self._client is not None
        raw = await self._client.get(self._k_profile(user_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def merge_user_profile(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None
        reserved = frozenset({"weak_tags", "tags", "all_tags_used", "updated_at"})
        k = self._k_profile(user_id)
        raw = await self._client.get(k)
        doc: dict[str, Any] = json.loads(raw) if raw else {}
        old_all: list[str] = []
        if isinstance(doc.get("all_tags_used"), list):
            old_all = [str(x).strip() for x in doc["all_tags_used"] if str(x).strip()]
        if patch.get("weak_tags") is not None:
            doc["weak_tags"] = list(patch["weak_tags"])
        if patch.get("tags") is not None:
            doc["tags"] = list(patch["tags"])
        if patch.get("all_tags_used") is not None:
            old_all = list(dict.fromkeys(old_all + [str(x).strip() for x in patch["all_tags_used"] if str(x).strip()]))
        for key, val in patch.items():
            if key in reserved:
                continue
            doc[key] = val
        weak = doc.get("weak_tags") if isinstance(doc.get("weak_tags"), list) else []
        tags_list = doc.get("tags") if isinstance(doc.get("tags"), list) else []
        weak_s = [str(x).strip() for x in weak if str(x).strip()]
        tags_s = [str(x).strip() for x in tags_list if str(x).strip()]
        doc["all_tags_used"] = list(dict.fromkeys(old_all + weak_s + tags_s))
        doc["updated_at"] = _now_iso()
        await self._client.set(k, json.dumps(doc, ensure_ascii=False))
        await self._maybe_ttl(k)
        return doc

    async def set_user_progress(
        self,
        user_id: str,
        *,
        weak_tags: list[str],
        difficulty: str,
        weights: tuple[float, float, float] | None,
        tests_hints: list[str] | None = None,
        requirements_hints: list[str] | None = None,
        constraints_hints: list[str] | None = None,
    ) -> dict[str, Any]:
        t1, t2, t3 = normalize_three_tags(weak_tags)
        w_payload: list[float] | None
        if weights is not None:
            w_payload = [float(weights[0]), float(weights[1]), float(weights[2])]
        else:
            w_payload = None
        payload: dict[str, Any] = {
            "weak_tags": [t1, t2, t3],
            "difficulty": difficulty,
            "weights": w_payload,
            "updated_at": _now_iso(),
        }
        if tests_hints is not None:
            payload["tests_hints"] = list(tests_hints)
        if requirements_hints is not None:
            payload["requirements_hints"] = list(requirements_hints)
        if constraints_hints is not None:
            payload["constraints_hints"] = list(constraints_hints)
        key = self._k_progress(user_id)
        await self._client.set(key, json.dumps(payload, ensure_ascii=False))
        await self._maybe_ttl(key)
        await self._sync_profile_weak_and_tags_used(user_id, [t1, t2, t3])
        return payload

    async def get_user_progress(self, user_id: str) -> dict[str, Any] | None:
        assert self._client is not None
        raw = await self._client.get(self._k_progress(user_id))
        if not raw:
            return None
        return json.loads(raw)


def merge_tag_mastery_observations_sync(
    redis_url: str, user_id: str, mastery: dict[str, float], *, ttl_seconds: int | None = None
) -> None:
    import redis as sync_redis

    if not mastery:
        return
    r = sync_redis.Redis.from_url(redis_url, decode_responses=True)
    k = f"edu:user:{user_id}:tag_stats"
    for tag, val in mastery.items():
        t = str(tag).strip()
        if not t:
            continue
        m = clamp_tag_score(val)
        if m is None:
            continue
        prev = r.hget(k, t)
        blob = merge_tag_sample_blob(prev, m)
        r.hset(k, t, blob)
    if ttl_seconds and ttl_seconds > 0:
        r.expire(k, int(ttl_seconds))
