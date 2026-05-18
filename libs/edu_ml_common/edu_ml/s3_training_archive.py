from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from edu_ml.s3_settings import get_s3_storage_settings
logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1

def _s3_client(region: str | None):
    if region:
        return boto3.client('s3', region_name=region)
    return boto3.client('s3')

def _key_prefix(subdir: str, user_id: str | None) -> str:
    s = get_s3_storage_settings()
    base = (s.s3_prefix_model_training or 'model-training-data').strip().strip('/')
    who = 'anonymous' if not user_id else str(user_id).replace('/', '_')
    now = datetime.now(timezone.utc)
    u = uuid.uuid4().hex
    return f'{base}/{subdir}/user_id={who}/{now:%Y/%m/%d}/{u}.json'

def try_archive_analyze_for_training(*, user_id: str | None=None, code: str, task: dict[str, Any] | None, task_context: str | None, analysis: str, tag_scores: dict[str, float] | None, report_json: dict[str, Any] | None, raw_model_completion: str | None=None, job_id: str | None=None) -> bool:
    s = get_s3_storage_settings()
    if not s.s3_bucket or not s.s3_model_training_export_enabled:
        return False
    record: dict[str, Any] = {'schema_version': SCHEMA_VERSION, 'kind': 'analyze', 'stored_at': datetime.now(timezone.utc).isoformat(), 'user_id': user_id, 'job_id': job_id, 'code': code, 'task': task, 'task_context': task_context, 'analysis': analysis, 'tag_scores': tag_scores or {}, 'report': report_json, 'raw_model_completion': raw_model_completion or ''}
    key = _key_prefix('analyze', user_id)
    body = json.dumps(record, ensure_ascii=False, default=str).encode('utf-8')
    try:
        _s3_client(s.aws_region).put_object(Bucket=s.s3_bucket, Key=key, Body=body, ContentType='application/json; charset=utf-8', Metadata={'kind': 'analyze', 'user-id': user_id or ''})
        logger.info('S3 model-training: analyze record s3://%s/%s', s.s3_bucket, key)
        return True
    except (ClientError, BotoCoreError, OSError, TypeError, ValueError) as e:
        logger.warning('S3 model-training export (analyze) failed: %s', e)
        return False

def try_archive_generate_task_for_training(*, user_id: str | None=None, task: dict[str, Any] | None, raw_completion: str, parse_ok: bool, tag1: str, tag2: str, tag3: str, difficulty: str, job_id: str | None=None) -> bool:
    s = get_s3_storage_settings()
    if not s.s3_bucket or not s.s3_model_training_export_enabled:
        return False
    record: dict[str, Any] = {'schema_version': SCHEMA_VERSION, 'kind': 'generate_task', 'stored_at': datetime.now(timezone.utc).isoformat(), 'user_id': user_id, 'job_id': job_id, 'task': task, 'raw_model_completion': raw_completion, 'parse_ok': parse_ok, 'request': {'tag1': tag1, 'tag2': tag2, 'tag3': tag3, 'difficulty': difficulty}}
    key = _key_prefix('generate-task', user_id)
    body = json.dumps(record, ensure_ascii=False, default=str).encode('utf-8')
    try:
        _s3_client(s.aws_region).put_object(Bucket=s.s3_bucket, Key=key, Body=body, ContentType='application/json; charset=utf-8', Metadata={'kind': 'generate_task', 'user-id': user_id or ''})
        logger.info('S3 model-training: generate-task record s3://%s/%s', s.s3_bucket, key)
        return True
    except (ClientError, BotoCoreError, OSError, TypeError, ValueError) as e:
        logger.warning('S3 model-training export (generate-task) failed: %s', e)
        return False
