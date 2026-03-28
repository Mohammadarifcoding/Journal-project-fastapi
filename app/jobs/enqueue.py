import logging

from app.jobs.rq_compat import apply_windows_rq_patch
from fastapi.concurrency import run_in_threadpool

apply_windows_rq_patch()

from rq import Retry
from app.jobs.queue import email_queue


logger = logging.getLogger(__name__)


RETRY_INTERVALS_SECONDS = [10, 30, 90, 300, 600]


async def enqueue_registration_email(user_id: str, email: str) -> str | None:
    job_id = f"email-registration-{user_id}"
    try:
        job = await run_in_threadpool(
            email_queue.enqueue,
            "app.jobs.email_jobs.send_registration_email_job",
            user_id,
            email,
            job_id=job_id,
            retry=Retry(max=5, interval=RETRY_INTERVALS_SECONDS),
            job_timeout=120,
            ttl=3600,
            result_ttl=86400,
            failure_ttl=604800,
        )
        return job_id

    except ValueError:
        logger.info("registration_email already enqueued user_id=%s", user_id)
        return job_id
    except Exception:
        logger.exception("registration_email enqueue failed user_id=%s", user_id)
        return None
