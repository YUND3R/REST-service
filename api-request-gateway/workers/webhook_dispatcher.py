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
                        await deliver_webhook(url, body, timeout=60.0)
                        await self._redis.xack(self._stream, self._group, msg_id)
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
