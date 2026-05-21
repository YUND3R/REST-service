from __future__ import annotations

import json
import time
from typing import Any

import redis.asyncio as redis

MIN_SCORE = 1.0
MAX_SCORE = 10.0
HISTORY_MAX = 100


def _base_profile_key(student_id: str) -> str:
    return f"student_profile:{student_id}"


def _tag_stats_key(student_id: str) -> str:
    return f"{_base_profile_key(student_id)}:tag_stats"


def _history_key(student_id: str) -> str:
    return f"{_base_profile_key(student_id)}:history"


def _clamp_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(MIN_SCORE, min(MAX_SCORE, score))


def tag_scores_from_analysis(analysis: dict[str, Any]) -> dict[str, float]:
    explicit = analysis.get("tag_scores")
    if isinstance(explicit, dict):
        out: dict[str, float] = {}
        for raw_tag, raw_score in explicit.items():
            tag = str(raw_tag).strip()
            score = _clamp_score(raw_score)
            if tag and score is not None:
                out[tag] = score
        if out:
            return out

    fallback_score = _clamp_score(analysis.get("score")) or 5.0
    raw_tags = analysis.get("tags") or []
    if not isinstance(raw_tags, list):
        return {}
    out = {}
    for raw_tag in raw_tags:
        tag = str(raw_tag).strip()
        if tag:
            out[tag] = fallback_score
    return out


def _merge_sample(prev_raw: str | None, score: float) -> str:
    if prev_raw:
        try:
            prev = json.loads(prev_raw)
            total = float(prev.get("sum", 0.0))
            count = int(prev.get("count", 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            total, count = 0.0, 0
    else:
        total, count = 0.0, 0
    return json.dumps({"sum": total + score, "count": count + 1}, ensure_ascii=False)


def _mean_score(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
        count = int(value.get("count", 0))
        if count <= 0:
            return None
        return float(value.get("sum", 0.0)) / count
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _parse_tag_stats(raw_stats: dict[str, str]) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for tag, raw in raw_stats.items():
        try:
            payload = json.loads(raw)
            total = float(payload.get("sum", 0.0))
            count = int(payload.get("count", 0))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if count < 0:
            continue
        if total < 0:
            total = 0.0
        out[str(tag)] = {"sum": total, "count": count}
    return out


async def merge_analysis_into_student_profile(
    r: redis.Redis,
    *,
    student_id: str,
    analysis: dict[str, Any],
    ttl_seconds: int | None = None,
) -> list[str]:
    tag_scores = tag_scores_from_analysis(analysis)
    if not tag_scores:
        return []

    profile_key = _base_profile_key(student_id)
    stats_key = _tag_stats_key(student_id)
    history_key = _history_key(student_id)

    history_row = json.dumps(
        {
            "kind": "analyze",
            "score": analysis.get("score"),
            "tags": list(tag_scores),
            "stored_at": time.time(),
        },
        ensure_ascii=False,
    )
    await r.lpush(history_key, history_row)
    await r.ltrim(history_key, 0, HISTORY_MAX - 1)

    for tag, score in tag_scores.items():
        prev = await r.hget(stats_key, tag)
        await r.hset(stats_key, tag, _merge_sample(prev, score))

    weakest = await get_weakest_tags(r, student_id=student_id, limit=3)
    raw_profile = await r.get(profile_key)
    try:
        profile = json.loads(raw_profile) if raw_profile else {}
    except json.JSONDecodeError:
        profile = {}

    previous_tags = profile.get("all_tags_used")
    if not isinstance(previous_tags, list):
        previous_tags = []
    merged_tags = list(dict.fromkeys([str(t).strip() for t in previous_tags if str(t).strip()] + list(tag_scores)))
    parsed_stats = _parse_tag_stats(await r.hgetall(stats_key))

    raw_history = await r.lrange(history_key, 0, HISTORY_MAX - 1)
    parsed_history: list[dict[str, Any]] = []
    for row in raw_history:
        try:
            parsed_history.append(json.loads(row))
        except json.JSONDecodeError:
            continue

    profile.update(
        {
            "id": student_id,
            "weak_tags": weakest,
            "tag_stats": parsed_stats,
            "history": parsed_history,
            "updated_at": time.time(),
        }
    )
    profile["all_tags_used"] = merged_tags

    await r.set(profile_key, json.dumps(profile, ensure_ascii=False), ex=ttl_seconds)
    if ttl_seconds:
        await r.expire(stats_key, ttl_seconds)
        await r.expire(history_key, ttl_seconds)
    return weakest


async def get_weakest_tags(r: redis.Redis, *, student_id: str, limit: int = 3) -> list[str]:
    rows = await r.hgetall(_tag_stats_key(student_id))
    scored: list[tuple[str, float]] = []
    for tag, raw in rows.items():
        mean = _mean_score(raw)
        if mean is not None:
            scored.append((str(tag), mean))
    scored.sort(key=lambda item: item[1])
    return [tag for tag, _ in scored[: max(0, limit)]]


async def get_student_profile(r: redis.Redis, *, student_id: str) -> dict[str, Any] | None:
    raw_profile = await r.get(_base_profile_key(student_id))
    if raw_profile:
        try:
            profile = json.loads(raw_profile)
            if isinstance(profile, dict):
                return profile
        except json.JSONDecodeError:
            pass

    stats = _parse_tag_stats(await r.hgetall(_tag_stats_key(student_id)))
    history_rows = await r.lrange(_history_key(student_id), 0, HISTORY_MAX - 1)
    history: list[dict[str, Any]] = []
    for row in history_rows:
        try:
            parsed = json.loads(row)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            history.append(parsed)

    if not stats and not history:
        return None

    return {
        "id": student_id,
        "weak_tags": await get_weakest_tags(r, student_id=student_id, limit=3),
        "tag_stats": stats,
        "history": history,
    }
