"""Standalone Background Worker Service.

Deploys alongside the web service on Render, sharing PostgreSQL and R2 / S3.
Polls pipeline_jobs table using row locking (FOR UPDATE SKIP LOCKED on Postgres),
processes documents asynchronously, handles retries with backoff, dead-letter routing,
and recovers crashed jobs via visibility timeout.

Entry point: python -m app.workers.service
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import signal
import sys
import time
from typing import Optional

from app.core.config import get_app_settings
from app.core.security import setup_secure_logging
from app.models.db import PipelineJobModel, get_db_session, init_db
from app.workers.dlq import DeadLetterQueueHandler
from app.workers.pipeline import process_document_payload

logger = setup_secure_logging("ecm.worker.service")

# Global graceful shutdown flag
_SHUTDOWN_REQUESTED = False


def _signal_handler(signum, frame):
    global _SHUTDOWN_REQUESTED
    logger.info(f"Signal {signum} received. Requesting graceful shutdown...")
    _SHUTDOWN_REQUESTED = True


def claim_next_job(db, queue_name: Optional[str] = None, visibility_timeout_sec: int = 300) -> Optional[PipelineJobModel]:
    """Atomically claim the next queued or timed-out job using row locking."""
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=visibility_timeout_sec)

    settings = get_app_settings()
    is_postgres = "postgres" in (settings.DATABASE_URL or "").lower()

    filters = [
        (PipelineJobModel.status == "QUEUED")
        | (
            (PipelineJobModel.status == "PROCESSING")
            & (PipelineJobModel.claimed_at < stale_cutoff)
        )
    ]
    if queue_name:
        filters.append(PipelineJobModel.queue_name == queue_name)

    query = db.query(PipelineJobModel).filter(*filters).order_by(PipelineJobModel.id.asc())

    if is_postgres:
        # PostgreSQL: FOR UPDATE SKIP LOCKED ensures zero contention across multi-worker instances
        job = query.with_for_update(skip_locked=True).first()
    else:
        # SQLite / Local mode
        job = query.first()

    if job:
        job.status = "PROCESSING"
        job.claimed_at = now
        job.retry_count = (job.retry_count or 0) + 1
        db.commit()
        db.refresh(job)
        return job

    return None


def execute_job(job: PipelineJobModel, max_retries: int = 3) -> bool:
    """Execute a single pipeline job with error capture and DLQ dispatch."""
    db = get_db_session()
    try:
        payload = json.loads(job.payload_json)
        logger.info(f"Processing job {job.job_id} for doc UID {payload.get('uid')} (attempt {job.retry_count})...")

        res = process_document_payload(payload)

        # Job succeeded
        job_db = db.query(PipelineJobModel).filter(PipelineJobModel.id == job.id).first()
        if job_db:
            if res.get("status") == "SUCCESS":
                job_db.status = "COMPLETED"
                job_db.error_message = None
                job_db.updated_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Job {job.job_id} successfully completed.")
                return True
            else:
                err_msg = res.get("error", "Pipeline processing returned failure status")
                return handle_job_failure(job_db, db, err_msg, max_retries)
        return False
    except Exception as e:
        logger.error(f"Unhandled exception processing job {job.job_id}: {e}", exc_info=True)
        job_db = db.query(PipelineJobModel).filter(PipelineJobModel.id == job.id).first()
        if job_db:
            return handle_job_failure(job_db, db, str(e), max_retries)
        return False
    finally:
        db.close()


def handle_job_failure(job: PipelineJobModel, db, error_msg: str, max_retries: int = 3) -> bool:
    """Record failure, evaluate retry backoff, or dispatch to Dead Letter Queue."""
    job.error_message = error_msg[:1000]
    job.updated_at = datetime.now(timezone.utc)

    if job.retry_count >= max_retries:
        # Reached maximum retries: route to Dead Letter Queue
        job.status = "FAILED"
        db.commit()
        logger.error(f"Job {job.job_id} permanently failed after {job.retry_count} attempts. Routing to DLQ.")
        try:
            dlq = DeadLetterQueueHandler()
            dlq.route_to_dlq(
                payload=json.loads(job.payload_json),
                error_stage="worker_service",
                error_detail=error_msg,
                retry_count=job.retry_count,
            )
        except Exception as dlq_err:
            logger.warning(f"Could not write to DLQ handler: {dlq_err}")
        return False
    else:
        # Transient failure: return to QUEUED for exponential backoff retry
        job.status = "QUEUED"
        db.commit()
        backoff_sec = 2 ** job.retry_count
        logger.warning(f"Job {job.job_id} failed transiently (attempt {job.retry_count}/{max_retries}). Retrying in {backoff_sec}s.")
        time.sleep(min(backoff_sec, 30))
        return False


def run_worker_loop(poll_interval: float = 1.0, max_jobs: Optional[int] = None):
    """Main worker loop continuously polling for jobs until shutdown."""
    init_db()
    processed_count = 0
    logger.info("Background Worker Service started. Polling for pipeline jobs...")

    while not _SHUTDOWN_REQUESTED:
        db = get_db_session()
        try:
            job = claim_next_job(db)
        finally:
            db.close()

        if job:
            execute_job(job)
            processed_count += 1
            if max_jobs and processed_count >= max_jobs:
                logger.info(f"Worker reached max_jobs={max_jobs}. Exiting loop.")
                break
        else:
            time.sleep(poll_interval)

    logger.info("Background Worker Service stopped cleanly.")


def main():
    """CLI Entry point for python -m app.workers.service."""
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    run_worker_loop()


if __name__ == "__main__":
    main()
