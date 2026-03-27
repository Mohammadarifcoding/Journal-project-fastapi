import logging
import os

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.background_jobs.tasks import (
    mark_stuck_analyses_job,
    process_queued_analyses_job,
    retry_failed_analyses_job,
)

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def should_run_scheduler_in_api() -> bool:
    return _env_bool("RUN_SCHEDULER_IN_API", False)


def _scheduler_listener(event: JobExecutionEvent) -> None:
    if event.exception:
        logger.error(
            "Scheduled job failed job_id=%s error=%s traceback=%s",
            event.job_id,
            event.exception,
            event.traceback,
        )
        return
    logger.info("Scheduled job finished job_id=%s", event.job_id)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        timezone = os.getenv("SCHEDULER_TIMEZONE", "UTC")
        _scheduler = AsyncIOScheduler(
            timezone=timezone,
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 30,
            },
        )
        _scheduler.add_listener(
            _scheduler_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        _scheduler.add_job(
            process_queued_analyses_job,
            trigger=CronTrigger(second="*/30"),
            id="analysis.process_queued",
            name="Process queued AI analyses",
            replace_existing=True,
        )
        _scheduler.add_job(
            retry_failed_analyses_job,
            trigger=CronTrigger(minute="*/2", second="5"),
            id="analysis.retry_failed",
            name="Retry failed AI analyses",
            replace_existing=True,
        )
        _scheduler.add_job(
            mark_stuck_analyses_job,
            trigger=CronTrigger(minute="*/5", second="10"),
            id="analysis.mark_stuck",
            name="Mark stuck AI analyses",
            replace_existing=True,
        )
    return _scheduler


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        logger.info("Scheduler already running")
        return
    scheduler.start()
    logger.info("Scheduler started with %s jobs", len(scheduler.get_jobs()))


def shutdown_scheduler() -> None:
    if _scheduler is None:
        return
    if not _scheduler.running:
        return
    _scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
