from __future__ import annotations

import json
import logging
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


def get_sqs_client(region: str | None):
    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    return boto3.client("sqs", **kwargs)


def send_message(*, queue_url: str, body: dict[str, Any], region: str | None = None) -> str | None:
    client = get_sqs_client(region)
    try:
        resp = client.send_message(QueueUrl=queue_url, MessageBody=json.dumps(body, ensure_ascii=False))
        return resp.get("MessageId")
    except (ClientError, BotoCoreError) as e:
        logger.error("SQS send_message failed: %s", e)
        raise
