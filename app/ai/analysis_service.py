import logging
import os
from datetime import datetime

from app.ai.generate_summary import LogEntry, generate_summary
from app.db import db

logger = logging.getLogger(__name__)

MAX_AI_RETRIES = max(1, int(os.getenv("AI_ANALYSIS_MAX_RETRIES", "3")))


def _utcnow() -> datetime:
    return datetime.utcnow()


def _trim_error_message(exc: Exception) -> str:
    return str(exc).strip()[:500] or "Unknown processing error"


async def queue_analysis_for_log(log_id: str) -> None:
    await db.aianalysis.upsert(
        where={"logId": log_id},
        data={
            "create": {
                "logId": log_id,
                "status": "queued",
                "key_points": [],
                "suggested_tags": [],
                "retryCount": 0,
            },
            "update": {
                "status": "queued",
                "lastError": None,
                "processingStartedAt": None,
            },
        },
    )


async def process_analysis_for_log(log_id: str, source: str = "api") -> bool:
    analysis = await db.aianalysis.find_unique(where={"logId": log_id})
    if not analysis:
        logger.warning("No analysis record found for log_id=%s", log_id)
        return False

    if analysis.status == "completed":
        logger.info("Skipping completed analysis for log_id=%s", log_id)
        return False

    retry_count = analysis.retryCount or 0
    if retry_count >= MAX_AI_RETRIES and analysis.status in {"failed", "dead_letter"}:
        logger.warning("Retry limit reached for log_id=%s", log_id)
        return False

    await db.aianalysis.update(
        where={"logId": log_id},
        data={
            "status": "processing",
            "processingStartedAt": _utcnow(),
            "lastError": None,
        },
    )

    log_entry = await db.log.find_unique(where={"id": log_id})
    if not log_entry:
        error_message = "Log not found"
        next_retry_count = retry_count + 1
        status = "dead_letter" if next_retry_count >= MAX_AI_RETRIES else "failed"
        await db.aianalysis.update(
            where={"logId": log_id},
            data={
                "status": status,
                "retryCount": next_retry_count,
                "lastError": error_message,
                "processingStartedAt": None,
            },
        )
        logger.error("%s for log_id=%s", error_message, log_id)
        return False

    payload = LogEntry(
        title=log_entry.title,
        content=log_entry.content,
        tags=log_entry.tags or [],
    )

    try:
        summary_result = await generate_summary(payload)
        result_data = summary_result.model_dump()

        await db.aianalysis.update(
            where={"logId": log_id},
            data={
                "summary": result_data.get("summary"),
                "key_points": result_data.get("key_points", []),
                "suggested_tags": result_data.get("suggested_tags", []),
                "learning_score": int(result_data.get("learning_score", 0)),
                "status": "completed",
                "lastError": None,
                "processingStartedAt": None,
            },
        )
        logger.info("Analysis completed for log_id=%s source=%s", log_id, source)
        return True
    except Exception as exc:
        next_retry_count = retry_count + 1
        status = "dead_letter" if next_retry_count >= MAX_AI_RETRIES else "failed"
        await db.aianalysis.update(
            where={"logId": log_id},
            data={
                "status": status,
                "retryCount": next_retry_count,
                "lastError": _trim_error_message(exc),
                "processingStartedAt": None,
            },
        )
        logger.exception("Analysis failed for log_id=%s source=%s", log_id, source)
        return False
