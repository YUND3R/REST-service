from __future__ import annotations
import json
import logging
import signal
import sys
import time
import boto3
from botocore.exceptions import ClientError
from analyze_svc.analyze_runtime import analyze_code, preload_model
from analyze_svc.settings_analyze import get_analyze_settings
from edu_ml.job_redis_sync import SyncJobStore
from edu_ml.redis_store import merge_tag_mastery_observations_sync
from edu_ml.schemas import AnalyzeTaskInput
from edu_ml.s3_training_archive import try_archive_analyze_for_training
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_stop = False

def _handle_stop(*_: object) -> None:
    global _stop
    _stop = True

def _handle_one(sqs, queue_url: str, jobs: SyncJobStore, message: dict) -> None:
    receipt = message['ReceiptHandle']
    body_raw: dict = {}
    try:
        body_raw = json.loads(message['Body'])
        job_id = body_raw['job_id']
        code = body_raw['code']
        task_context = body_raw.get('task_context')
        t_raw = body_raw.get('task')
        task = AnalyzeTaskInput.model_validate(t_raw) if isinstance(t_raw, dict) and t_raw else None
        if task is None and not task_context:
            raise ValueError('Нужен task или task_context')
        jobs.mark_processing(job_id)
        result = analyze_code(code=code, task=task, task_context=task_context)
        text = result.analysis
        scores = result.tag_scores or {}
        out: dict = {'analysis': text, 'tag_scores': scores}
        if result.report_json is not None:
            out['report'] = result.report_json
        jobs.mark_completed(job_id, out)
        task_dict = task.model_dump(mode='json') if task else None
        try_archive_analyze_for_training(user_id=body_raw.get('user_id'), code=code, task=task_dict, task_context=task_context, analysis=text, tag_scores=scores, report_json=result.report_json, raw_model_completion=result.raw_completion, job_id=job_id)
        uid = body_raw.get('user_id')
        if uid and scores:
            try:
                s = get_analyze_settings()
                if s.redis_url:
                    merge_tag_mastery_observations_sync(s.redis_url, str(uid), scores, ttl_seconds=s.redis_ttl_seconds)
            except Exception as ex:
                logger.warning('tag_stats sync failed (%s)', type(ex).__name__)
    except Exception as e:
        logger.exception('Analyze job failed')
        jid = body_raw.get('job_id') if isinstance(body_raw, dict) else None
        if jid:
            try:
                jobs.mark_failed(jid, str(e))
            except Exception:
                logger.exception('mark_failed failed')
    finally:
        try:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        except ClientError as e:
            logger.error('delete_message failed: %s', e)

def main() -> None:
    global _stop
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    settings = get_analyze_settings()
    if not settings.redis_url:
        logger.error('Нужен REDIS_URL для статусов заданий')
        sys.exit(1)
    if not settings.sqs_analyze_queue_url:
        logger.error('Нужен SQS_ANALYZE_QUEUE_URL')
        sys.exit(1)
    if settings.preload_model:
        preload_model()
    region = settings.aws_region
    sqs = boto3.client('sqs', region_name=region) if region else boto3.client('sqs')
    jobs = SyncJobStore(settings.redis_url, 'edu:job:analyze:', ttl_seconds=settings.job_result_ttl_seconds)
    qurl = settings.sqs_analyze_queue_url
    vis = min(settings.sqs_visibility_timeout_seconds, 43200)
    wait = 20
    logger.info('SQS worker (analyze) started, queue=%s', qurl)
    while not _stop:
        try:
            resp = sqs.receive_message(QueueUrl=qurl, MaxNumberOfMessages=1, WaitTimeSeconds=wait, VisibilityTimeout=vis)
            for m in resp.get('Messages', []):
                if _stop:
                    break
                _handle_one(sqs, qurl, jobs, m)
        except ClientError as e:
            logger.error('SQS receive error: %s', e)
            time.sleep(5)
    jobs.close()
    logger.info('Worker stopped')
if __name__ == '__main__':
    main()
