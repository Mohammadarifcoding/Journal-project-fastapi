import asyncio
import logging
import os
from datetime import datetime, timedelta

from app.ai.analysis_service import MAX_AI_RETRIES, process_analysis_for_log
from app.db import db

logger = logging.getLogger(__name__)

PROCESS_BATCH_SIZE = max(1, int(os.getenv("AI_ANALYSIS_BATCH_SIZE", "5")))
PROCESSING_TIMEOUT_MINUTES = max(
    1, int(os.getenv("AI_ANALYSIS_PROCESSING_TIMEOUT_MINUTES", "15"))
)

_queue_job_lock = asyncio.Lock()
_retry_job_lock = asyncio.Lock()
_stuck_job_lock = asyncio.Lock()


def _utcnow() -> datetime:
    return datetime.utcnow()


async def process_queued_analyses_job() -> None:
    if _queue_job_lock.locked():
        logger.warning("Skipping queued analyses job: previous run still active")
        return

    async with _queue_job_lock:
        queued_items = await db.aianalysis.find_many(
            where={"status": "queued"},
            order={"createdAt": "asc"},
            take=PROCESS_BATCH_SIZE,
        )

        if not queued_items:
            return

        logger.info("Processing %s queued analyses", len(queued_items))
        for analysis in queued_items:
            await process_analysis_for_log(analysis.logId, source="cron:queued")


async def retry_failed_analyses_job() -> None:
    if _retry_job_lock.locked():
        logger.warning("Skipping retry job: previous run still active")
        return

    async with _retry_job_lock:
        failed_items = await db.aianalysis.find_many(
            where={"status": "failed", "retryCount": {"lt": MAX_AI_RETRIES}},
            order={"createdAt": "asc"},
            take=PROCESS_BATCH_SIZE,
        )

        if not failed_items:
            return

        logger.info("Retrying %s failed analyses", len(failed_items))
        for analysis in failed_items:
            await process_analysis_for_log(analysis.logId, source="cron:retry")


async def mark_stuck_analyses_job() -> None:
    if _stuck_job_lock.locked():
        logger.warning("Skipping stuck-analysis job: previous run still active")
        return

    async with _stuck_job_lock:
        stale_cutoff = _utcnow() - timedelta(minutes=PROCESSING_TIMEOUT_MINUTES)
        stuck_items = await db.aianalysis.find_many(
            where={
                "status": "processing",
                "processingStartedAt": {"lt": stale_cutoff},
            },
            order={"processingStartedAt": "asc"},
            take=PROCESS_BATCH_SIZE,
        )

        if not stuck_items:
            return

        logger.warning("Found %s stuck analyses", len(stuck_items))
        for analysis in stuck_items:
            next_retry_count = (analysis.retryCount or 0) + 1
            status = "dead_letter" if next_retry_count >= MAX_AI_RETRIES else "failed"
            await db.aianalysis.update(
                where={"id": analysis.id},
                data={
                    "status": status,
                    "retryCount": next_retry_count,
                    "lastError": "Timed out while processing",
                    "processingStartedAt": None,
                },
            )
