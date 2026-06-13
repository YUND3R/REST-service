from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from typing import Any

import redis.asyncio as redis
from redis.exceptions import ResponseError

from gateway.config import get_settings
from gateway.services.webhook import deliver_webhook

logger = logging.getLogger(__name__)


class WebhookDispatcher:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis = redis.from_url(self._settings.redis_url, decode_responses=True)
        self._stream = self._settings.stream_webhook
        self._group = os.environ.get("STREAM_GROUP_WEBHOOK", "webhook_dispatchers")
        self._consumer = os.environ.get("CONSUMER_NAME", socket.gethostname())

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_create(self._stream, self._group, id="0-0", mkstream=True)
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def run_forever(self) -> None:
        await self.ensure_group()
        max_attempts = int(os.environ.get("WEBHOOK_MAX_ATTEMPTS", "5"))
        base_retry_seconds = float(os.environ.get("WEBHOOK_RETRY_BASE_SECONDS", "2"))
        max_retry_seconds = float(os.environ.get("WEBHOOK_RETRY_MAX_SECONDS", "60"))
        while True:
            resp = await self._redis.xreadgroup(
                self._group,
                self._consumer,
                {self._stream: ">"},
                count=int(os.environ.get("WEBHOOK_STREAM_BATCH", "8")),
                block=5000,
            )
            if not resp:
                continue
            for _stream_name, messages in resp:
                for msg_id, fields in messages:
                    try:
                        raw = fields.get("data") or "{}"
                        event: dict[str, Any] = json.loads(raw)
                        url = str(event["webhook_url"])
                        body = event["body"]
                        if not isinstance(body, dict):
                            raise ValueError("webhook body must be an object")
                        ok = await deliver_webhook(url, body, timeout=60.0)
                        if ok:
                            await self._redis.xack(self._stream, self._group, msg_id)
                            continue
                        attempts = int(fields.get("attempts") or "0") + 1
                        if attempts >= max_attempts:
                            logger.error(
                                "webhook dispatch dropped after max attempts: %s",
                                event.get("task_id", "<unknown-task>"),
                            )
                            await self._redis.xack(self._stream, self._group, msg_id)
                            continue
                        retry_delay = min(max_retry_seconds, base_retry_seconds * (2 ** (attempts - 1)))
                        retry_event = {
                            "task_id": event.get("task_id"),
                            "webhook_url": url,
                            "body": body,
                            "attempts": attempts,
                        }
                        await self._redis.xadd(self._stream, {"data": json.dumps(retry_event, ensure_ascii=False)})
                        await self._redis.xack(self._stream, self._group, msg_id)
                        await asyncio.sleep(retry_delay)
                    except Exception as e:
                        logger.exception("webhook dispatch failed: %s", e)
                        await self._redis.xack(self._stream, self._group, msg_id)


async def amain() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    dispatcher = WebhookDispatcher()
    await dispatcher.run_forever()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
