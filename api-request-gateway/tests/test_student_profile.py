from __future__ import annotations

import json

import pytest

from gateway.services.student_profile import (
    get_weakest_tags,
    merge_analysis_into_student_profile,
    tag_scores_from_analysis,
)


class FakeRedis:
    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.expires: dict[str, int] = {}

    async def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    async def hset(self, key: str, field: str, value: str) -> None:
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def lpush(self, key: str, value: str) -> None:
        self.strings.setdefault(f"__list__{key}", "[]")
        items = json.loads(self.strings[f"__list__{key}"])
        items.insert(0, value)
        self.strings[f"__list__{key}"] = json.dumps(items, ensure_ascii=False)

    async def ltrim(self, key: str, start: int, stop: int) -> None:
        items = json.loads(self.strings.get(f"__list__{key}", "[]"))
        self.strings[f"__list__{key}"] = json.dumps(items[start : stop + 1], ensure_ascii=False)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        items = json.loads(self.strings.get(f"__list__{key}", "[]"))
        return items[start : stop + 1]

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.strings[key] = value
        if ex is not None:
            self.expires[key] = ex

    async def expire(self, key: str, ttl: int) -> None:
        self.expires[key] = ttl


def test_tag_scores_from_analysis_prefers_explicit_scores() -> None:
    assert tag_scores_from_analysis({"score": 9, "tags": ["Fallback"], "tag_scores": {"Arrays": 3}}) == {"Arrays": 3.0}


def test_tag_scores_from_analysis_uses_overall_score_for_tags() -> None:
    assert tag_scores_from_analysis({"score": 4, "tags": ["SQL", "Joins"]}) == {"SQL": 4.0, "Joins": 4.0}


@pytest.mark.asyncio
async def test_merge_analysis_updates_profile_and_weakest_tags() -> None:
    r = FakeRedis()
    await merge_analysis_into_student_profile(
        r,
        student_id="student-1",
        analysis={"score": 9, "tags": ["Arrays"]},
        ttl_seconds=60,
    )
    weakest = await merge_analysis_into_student_profile(
        r,
        student_id="student-1",
        analysis={"score": 2, "tags": ["Graphs"]},
        ttl_seconds=60,
    )

    assert weakest == ["Graphs", "Arrays"]
    assert await get_weakest_tags(r, student_id="student-1", limit=1) == ["Graphs"]
    profile = json.loads(r.strings["student_profile:student-1"])
    assert profile["id"] == "student-1"
    assert profile["weak_tags"] == ["Graphs", "Arrays"]
    assert "tag_stats" in profile and "Graphs" in profile["tag_stats"]
    assert "history" in profile and profile["history"][0]["kind"] == "analyze"
    assert profile["all_tags_used"] == ["Arrays", "Graphs"]
    assert r.expires["student_profile:student-1"] == 60
    assert r.expires["student_profile:student-1:tag_stats"] == 60
    assert r.expires["student_profile:student-1:history"] == 60
