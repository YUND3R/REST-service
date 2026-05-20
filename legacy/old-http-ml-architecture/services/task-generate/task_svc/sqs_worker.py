from __future__ import annotations

import json
import logging
import signal
import sys
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError
from edu_ml.job_redis_sync import SyncJobStore
from edu_ml.s3_training_archive import try_archive_generate_task_for_training
from edu_ml.schemas import GenerateTaskRequest, coerce_ml_task

from task_svc.generate_runtime import generate_broken_task, preload_model
from task_svc.settings_generate import get_generate_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_stop = False


def _handle_stop(*_: object) -> None:
    global _stop
    _stop = True


def _handle_one(sqs, queue_url: str, jobs: SyncJobStore, message: dict) -> None:
    receipt = message["ReceiptHandle"]
    body_raw: dict[str, Any] = {}
    try:
        body_raw = json.loads(message["Body"])
        job_id = body_raw["job_id"]
        payload = body_raw["payload"]
        req = GenerateTaskRequest.model_validate(payload)
        jobs.mark_processing(job_id)
        raw, task, ok = generate_broken_task(
            tag1=req.tag1,
            tag2=req.tag2,
            tag3=req.tag3,
            difficulty=req.difficulty,
            weights=req.weights,
            tests_hints=req.tests_hints,
            requirements_hints=req.requirements_hints,
            constraints_hints=req.constraints_hints,
        )
        typed = coerce_ml_task(task)
        result = {
            "task": task,
            "task_typed": typed.model_dump() if typed else None,
            "raw_completion": raw,
            "parse_ok": ok,
        }
        jobs.mark_completed(job_id, result)
        try_archive_generate_task_for_training(
            user_id=body_raw.get("user_id"),
            task=task,
            raw_completion=raw,
            parse_ok=ok,
            tag1=req.tag1,
            tag2=req.tag2,
            tag3=req.tag3,
            difficulty=req.difficulty,
            job_id=job_id,
        )
    except Exception as e:
        logger.exception("Generate job failed")
        jid = body_raw.get("job_id") if isinstance(body_raw, dict) else None
        if jid:
            try:
                jobs.mark_failed(jid, str(e))
            except Exception:
                logger.exception("mark_failed failed")
    finally:
        try:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        except ClientError as e:
            logger.error("delete_message failed: %s", e)


def main() -> None:
    global _stop
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    settings = get_generate_settings()
    if not settings.redis_url:
        logger.error("Нужен REDIS_URL для статусов заданий")
        sys.exit(1)
    if not settings.sqs_generate_queue_url:
        logger.error("Нужен SQS_GENERATE_QUEUE_URL")
        sys.exit(1)
    if settings.preload_model:
        preload_model()
    region = settings.aws_region
    sqs = boto3.client("sqs", region_name=region) if region else boto3.client("sqs")
    jobs = SyncJobStore(settings.redis_url, "edu:job:generate:", ttl_seconds=settings.job_result_ttl_seconds)
    qurl = settings.sqs_generate_queue_url
    vis = min(settings.sqs_visibility_timeout_seconds, 43200)
    wait = 20
    logger.info("SQS worker (generate) started, queue=%s", qurl)
    while not _stop:
        try:
            resp = sqs.receive_message(
                QueueUrl=qurl, MaxNumberOfMessages=1, WaitTimeSeconds=wait, VisibilityTimeout=vis
            )
            for m in resp.get("Messages", []):
                if _stop:
                    break
                _handle_one(sqs, qurl, jobs, m)
        except ClientError as e:
            logger.error("SQS receive error: %s", e)
            time.sleep(5)
    jobs.close()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
