import logging
import os
import socket
from datetime import datetime, timedelta
from uuid import uuid4

from prisma import Json, enums

from app.db import db
from app.jobs.enqueue import enqueue_registration_email

logger = logging.getLogger(__name__)

OUTBOX_BATCH_SIZE = max(1, int(os.getenv("EMAIL_OUTBOX_BATCH_SIZE", "20")))
OUTBOX_LOCK_TIMEOUT_SECONDS = max(
    30, int(os.getenv("EMAIL_OUTBOX_LOCK_TIMEOUT_SECONDS", "120"))
)
OUTBOX_MAX_RETRIES = max(1, int(os.getenv("EMAIL_OUTBOX_MAX_RETRIES", "10")))
OUTBOX_RETRY_DELAYS = (10, 30, 120, 300, 600)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _dispatch_owner(source: str) -> str:
    return f"{source}:{socket.gethostname()}:{uuid4().hex[:8]}"


def _next_retry_at(attempt: int) -> datetime:
    index = min(max(attempt - 1, 0), len(OUTBOX_RETRY_DELAYS) - 1)
    return _utcnow() + timedelta(seconds=OUTBOX_RETRY_DELAYS[index])


async def create_registration_outbox_job(tx, user_id: str, email: str) -> str:
    job = await tx.job.create(
        data={
            "type": enums.JobType.EMAIL,
            "status": enums.Status.PENDING,
            "payload": Json(
                {
                    "kind": "registration_email",
                    "user_id": user_id,
                    "email": email,
                }
            ),
            "retryCount": 0,
            "maxRetries": OUTBOX_MAX_RETRIES,
            "scheduledAt": _utcnow(),
            "priority": 0,
        }
    )
    return job.id


async def dispatch_outbox_job(job_id: str, source: str = "api") -> bool:
    now = _utcnow()
    stale_cutoff = now - timedelta(seconds=OUTBOX_LOCK_TIMEOUT_SECONDS)

    claimed = await db.job.update_many(
        where={
            "id": job_id,
            "type": enums.JobType.EMAIL,
            "OR": [
                {
                    "status": {"in": [enums.Status.PENDING, enums.Status.FAILED]},
                    "retryCount": {"lt": OUTBOX_MAX_RETRIES},
                    "OR": [{"scheduledAt": None}, {"scheduledAt": {"lte": now}}],
                },
                {
                    "status": enums.Status.PROCESSING,
                    "lockedAt": {"lt": stale_cutoff},
                },
            ],
        },
        data={
            "status": enums.Status.PROCESSING,
            "lockedBy": _dispatch_owner(source),
            "lockedAt": now,
        },
    )

    if claimed != 1:
        return False

    job = await db.job.find_unique(where={"id": job_id})
    if not job:
        return False

    payload = job.payload or {}
    user_id = str(payload.get("user_id", "")).strip()
    email = str(payload.get("email", "")).strip()

    if not user_id or not email:
        await db.job.update(
            where={"id": job.id},
            data={
                "status": enums.Status.FAILED,
                "retryCount": job.maxRetries,
                "lastError": "Invalid registration email payload",
                "scheduledAt": None,
                "lockedBy": None,
                "lockedAt": None,
            },
        )
        return False

    try:
        redis_job_id = await enqueue_registration_email(user_id, email)
        if not redis_job_id:
            raise RuntimeError("Failed to enqueue registration email to Redis")

        await db.job.update(
            where={"id": job.id},
            data={
                "status": enums.Status.COMPLETED,
                "result": Json(
                    {
                        "redis_job_id": redis_job_id,
                        "dispatchedAt": _utcnow().isoformat(),
                        "source": source,
                    }
                ),
                "lastError": None,
                "scheduledAt": None,
                "lockedBy": None,
                "lockedAt": None,
            },
        )
        logger.info(
            "Outbox job dispatched job_id=%s redis_job_id=%s source=%s",
            job.id,
            redis_job_id,
            source,
        )
        return True
    except Exception as exc:
        next_retry_count = (job.retryCount or 0) + 1
        can_retry = next_retry_count < (job.maxRetries or OUTBOX_MAX_RETRIES)

        await db.job.update(
            where={"id": job.id},
            data={
                "status": enums.Status.FAILED,
                "retryCount": next_retry_count,
                "lastError": str(exc).strip()[:500] or "Outbox dispatch failed",
                "scheduledAt": _next_retry_at(next_retry_count) if can_retry else None,
                "lockedBy": None,
                "lockedAt": None,
            },
        )
        logger.exception("Outbox dispatch failed job_id=%s source=%s", job.id, source)
        return False


async def dispatch_pending_outbox_jobs(source: str = "relay") -> int:
    now = _utcnow()
    stale_cutoff = now - timedelta(seconds=OUTBOX_LOCK_TIMEOUT_SECONDS)

    jobs = await db.job.find_many(
        where={
            "type": enums.JobType.EMAIL,
            "OR": [
                {
                    "status": {"in": [enums.Status.PENDING, enums.Status.FAILED]},
                    "retryCount": {"lt": OUTBOX_MAX_RETRIES},
                    "OR": [{"scheduledAt": None}, {"scheduledAt": {"lte": now}}],
                },
                {
                    "status": enums.Status.PROCESSING,
                    "lockedAt": {"lt": stale_cutoff},
                },
            ],
        },
        order={"createdAt": "asc"},
        take=OUTBOX_BATCH_SIZE,
    )

    dispatched = 0
    for job in jobs:
        if await dispatch_outbox_job(job.id, source=source):
            dispatched += 1

    return dispatched
