import asyncio
import logging
import os


from app.email.email import send_registration_email
from app.jobs.queue import email_queue, redis_conn
from app.jobs.rq_compat import apply_windows_rq_patch

apply_windows_rq_patch()

from rq import get_current_job


logger = logging.getLogger(__name__)

Lock_ttl_seconds = 120
IDEMPOTENCY_TTL_SECONDS = 60 * 60 * 24 * 15


async def send_registration_email_job(user_id: int, email: str):
    job = get_current_job()
    job_id = job.id if job else "unknown"
    sent_key = f"idem:email:registration:{user_id}"
    if redis_conn.get(sent_key):
        logger.info(
            "registration_email skipped already_sent user_id=%s job_id=%s",
            user_id,
            job_id,
        )
        return {"status": "skipped", "reason": "already_sent", "job_id": job_id}
    lock_key = f"lock:email:registration:{user_id}"
    lock = redis_conn.lock(lock_key, timeout=Lock_ttl_seconds, blocking_timeout=1)

    if not lock.acquire(blocking=False):
        logger.info(
            "registration_email skipped locked user_id=%s job_id=%s",
            user_id,
            job_id,
        )
        return {"status": "skipped", "reason": "locked", "job_id": job_id}

    try:
        await send_registration_email(email)
        redis_conn.set(sent_key, "1", ex=IDEMPOTENCY_TTL_SECONDS)

        logger.info(
            "registration_email sent user_id=%s job_id=%s",
            user_id,
            job_id,
        )
        return {"status": "sent", "job_id": job_id}
    except Exception:
        logger.exception(
            "registration_email failed user_id=%s job_id=%s",
            user_id,
            job_id,
        )
        raise
    finally:
        if lock.owned():
            lock.release()
