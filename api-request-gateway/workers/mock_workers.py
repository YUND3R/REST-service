# Mock workers for integration testing without GPU inference.
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import socket
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

from gateway.config import get_settings
from gateway.services.cache import analyze_cache_key, generate_cache_key
from gateway.services.queue import STATUS_FAILED, STATUS_PROCESSING, QueueService
from gateway.services.student_profile import merge_analysis_into_student_profile
from models.code_analyze import score_to_difficulty
from workers.analyze_worker import persist_analysis
from workers.generate_worker import persist_generated
from workers.pipeline_worker import persist_pipeline

logger = logging.getLogger(__name__)

STUB_MODEL_MESSAGE = os.environ.get(
    "STUB_MODEL_MESSAGE",
    "Модель успешно бы отработала текст",
)

_PROCESSING_DELAY_SEC = float(os.environ.get("MOCK_PROCESSING_DELAY_SEC", "1.5"))


def _code_lines(code: str) -> list[str]:
    return code.splitlines() or [code]


def _infer_tags(code: str, task_description: str) -> list[str]:
    text = f"{task_description}\n{code}".lower()
    tags: list[str] = []
    rules = [
        (("def ", "lambda"), "functions"),
        (("for ", "while "), "loops"),
        (("class ",), "oop"),
        (("import ", "from "), "modules"),
        (("try:", "except"), "exceptions"),
        (("list", "dict", "set("), "data_structures"),
        (("sql", "select ", "insert "), "sql"),
        (("print(",), "io"),
        (("return ",), "control_flow"),
    ]
    for keys, tag in rules:
        if any(k in text for k in keys):
            tags.append(tag)
    if not tags:
        tags.append("python")
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:6]


def _find_line(code: str, pattern: str) -> int | None:
    for i, line in enumerate(_code_lines(code), start=1):
        if re.search(pattern, line):
            return i
    return None


def mock_analysis(code: str, task_description: str = "") -> dict[str, Any]:
    """Production-shaped analysis; inference is heuristic (no GPU model)."""
    lines = _code_lines(code)
    tags = _infer_tags(code, task_description)
    weak_spots: list[dict[str, Any]] = []
    score = 8

    if "pass" in code and "def " in code:
        ln = _find_line(code, r"^\s*pass\s*$")
        weak_spots.append(
            {
                "line": ln,
                "issue": "Функция пока не реализована — заглушка pass.",
                "hint": "Добавьте тело функции согласно условию задачи.",
            }
        )
        score -= 2

    if re.search(r"print\s*\(", code) and "return " not in code:
        ln = _find_line(code, r"print\s*\(")
        weak_spots.append(
            {
                "line": ln,
                "issue": "Результат выводится через print, а не возвращается.",
                "hint": "Для автопроверки обычно нужен return значения.",
            }
        )
        score -= 1

    if "def " in code and "return " not in code:
        ln = _find_line(code, r"def\s+\w+")
        weak_spots.append(
            {
                "line": ln,
                "issue": "Функция объявлена без return — возможен неявный None.",
                "hint": "Явно верните результат вычисления.",
            }
        )
        score -= 1

    if re.search(r"except\s*:", code):
        ln = _find_line(code, r"except\s*:")
        weak_spots.append(
            {
                "line": ln,
                "issue": "Перехват исключений без указания типа.",
                "hint": "Ловите конкретные исключения, чтобы не скрывать ошибки.",
            }
        )
        score -= 1

    if len(lines) > 40:
        weak_spots.append(
            {
                "line": None,
                "issue": "Решение получилось объёмным — стоит разбить на функции.",
                "hint": "Выделите вспомогательные шаги в отдельные функции.",
            }
        )
        score -= 1

    score = max(1, min(10, score))
    if not weak_spots:
        weak_spots.append(
            {
                "line": None,
                "issue": "Явных синтаксических проблем не найдено.",
                "hint": "Проверьте граничные случаи и соответствие условию.",
            }
        )

    recommendations = [
        STUB_MODEL_MESSAGE,
        "Сверьте решение с формулировкой задачи и прогоните тесты на краевых значениях.",
    ]
    if "loops" in tags:
        recommendations.append("Для циклов проверьте условие выхода и инвариант.")
    if score <= 5:
        recommendations.append("Начните с простого рабочего варианта, затем улучшайте структуру.")

    return {
        "score": score,
        "weak_spots": weak_spots,
        "tags": tags,
        "recommendations": recommendations,
    }


_TASK_TEMPLATES: dict[str, dict[str, Any]] = {
    "easy": {
        "title": "Исправьте функцию сложения",
        "task_context": "В функции add_one допущена арифметическая ошибка. Верните корректное значение.",
        "tests": [
            {"input": "add_one(0)", "expected": 1},
            {"input": "add_one(4)", "expected": 5},
        ],
        "broken_code": "def add_one(n):\n    return n - 1\n",
    },
    "medium": {
        "title": "Найдите ошибку в фильтрации списка",
        "task_context": "Функция должна оставлять только чётные положительные числа в исходном порядке.",
        "tests": [
            {"input": "even_positives([1, 2, 3, 4])", "expected": [2, 4]},
            {"input": "even_positives([-2, 0, 5])", "expected": []},
        ],
        "broken_code": (
            "def even_positives(nums):\n"
            "    out = []\n"
            "    for x in nums:\n"
            "        if x % 2 == 0 and x > 0:\n"
            "            out.append(x)\n"
            "    return out[::-1]\n"
        ),
    },
    "hard": {
        "title": "Исправьте обход графа",
        "task_context": "Реализуйте BFS: верните длины кратчайших путей от start до всех вершин.",
        "tests": [
            {"input": "bfs_distances({0:[1],1:[2],2:[]}, 0)", "expected": {0: 0, 1: 1, 2: 2}},
        ],
        "broken_code": (
            "from collections import deque\n\n"
            "def bfs_distances(adj, start):\n"
            "    dist = {start: 0}\n"
            "    q = deque([start])\n"
            "    while q:\n"
            "        u = q.popleft()\n"
            "        for v in adj.get(u, []):\n"
            "            if v not in dist:\n"
            "                dist[v] = dist[u]\n"
            "                q.append(v)\n"
            "    return dist\n"
        ),
    },
}


def mock_generated_task(tags: list[str], difficulty: str) -> dict[str, Any]:
    template = _TASK_TEMPLATES.get(difficulty, _TASK_TEMPLATES["medium"])
    primary = tags[0] if tags else "python"
    topic_tags = {tag: max(1, len(tags) - i) for i, tag in enumerate(tags[:5])}
    if not topic_tags:
        topic_tags = {primary: 2, "python": 1}
    return {
        "title": template["title"],
        "difficulty": difficulty,
        "topic_tags": topic_tags,
        "task_context": template["task_context"],
        "tests": list(template["tests"]),
        "broken_code": template["broken_code"],
    }


async def _simulate_model_latency() -> None:
    if _PROCESSING_DELAY_SEC <= 0:
        return
    jitter = random.uniform(0, min(0.8, _PROCESSING_DELAY_SEC * 0.3))
    await asyncio.sleep(_PROCESSING_DELAY_SEC + jitter)


class MockWorkers:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
        self._queue = QueueService(self._redis)
        self._consumer = os.environ.get("CONSUMER_NAME", socket.gethostname())

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="0-0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume(
        self,
        stream: str,
        group: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        await self.ensure_group(stream, group)
        while True:
            resp = await self._redis.xreadgroup(
                group,
                self._consumer,
                {stream: ">"},
                count=int(os.environ.get("STREAM_BATCH", "4")),
                block=5000,
            )
            if not resp:
                continue
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    job: dict[str, Any] = {}
                    try:
                        job = json.loads(fields.get("data") or "{}")
                        await handler(job)
                        await self._redis.xack(stream, group, msg_id)
                    except Exception as e:
                        logger.exception("Mock worker job failed: %s", e)
                        if job.get("task_id"):
                            await self._queue.set_status(str(job["task_id"]), STATUS_FAILED, error=str(e))
                        await self._redis.xack(stream, group, msg_id)

    async def handle_analyze(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(str(job["student_uuid"]))
        task_description = str(job["task_description"])
        code = str(job["code"])
        webhook_url = str(job["webhook_url"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)
        await _simulate_model_latency()
        analysis = mock_analysis(code, task_description)
        await persist_analysis(student_uuid, task_description, code, analysis)

        body = {"student_id": student_external, "analysis": analysis}
        await self._queue.complete_with_result(task_id, body)
        await self._queue.enqueue_webhook(webhook_url, body, task_id=task_id)

    async def handle_generate(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(str(job["student_uuid"]))
        tags = list(job.get("tags") or ["python"])
        difficulty = str(job.get("difficulty") or "medium")
        webhook_url = str(job["webhook_url"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)
        await _simulate_model_latency()
        generated = mock_generated_task(tags, difficulty)
        await persist_generated(student_uuid, tags, difficulty, generated, None)

        body = {"student_id": student_external, "generated_task": generated}
        await self._queue.complete_with_result(task_id, body)
        await self._queue.enqueue_webhook(webhook_url, body, task_id=task_id)

    async def handle_pipeline(self, job: dict[str, Any]) -> None:
        task_id = str(job["task_id"])
        student_external = str(job["student_external_id"])
        student_uuid = uuid.UUID(str(job["student_uuid"]))
        task_description = str(job["task_description"])
        code = str(job["code"])
        webhook_url = str(job["webhook_url"])

        await self._queue.set_status(task_id, STATUS_PROCESSING)
        await _simulate_model_latency()
        analysis = mock_analysis(code, task_description)
        difficulty = score_to_difficulty(int(analysis["score"]))
        profile_tags = await merge_analysis_into_student_profile(
            self._redis,
            student_id=str(student_uuid),
            analysis=analysis,
            ttl_seconds=self._settings.cache_ttl_seconds,
        )
        tags = profile_tags or list(analysis.get("tags") or ["python"])
        await _simulate_model_latency()
        generated = mock_generated_task(tags, difficulty)
        await persist_pipeline(student_uuid, task_description, code, analysis, generated, difficulty, tags)

        body = {
            "student_id": student_external,
            "analysis": analysis,
            "generated_task": generated,
            "profile_tags_used": tags,
        }
        await self._queue.complete_with_result(task_id, body)
        await self._queue.enqueue_webhook(webhook_url, body, task_id=task_id)

        await self._redis.set(
            analyze_cache_key(task_description, code),
            json.dumps(analysis, ensure_ascii=False),
            ex=self._settings.cache_ttl_seconds,
        )
        await self._redis.set(
            generate_cache_key(tags, difficulty),
            json.dumps(generated, ensure_ascii=False),
            ex=self._settings.cache_ttl_seconds,
        )

    async def run(self) -> None:
        await asyncio.gather(
            self.consume(self._settings.stream_analyze, "analyze_workers", self.handle_analyze),
            self.consume(self._settings.stream_generate, "generate_workers", self.handle_generate),
            self.consume(self._settings.stream_pipeline, "pipeline_workers", self.handle_pipeline),
        )


async def amain() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logger.info("Mock workers started (production-shaped responses, no GPU inference)")
    await MockWorkers().run()


if __name__ == "__main__":
    asyncio.run(amain())
