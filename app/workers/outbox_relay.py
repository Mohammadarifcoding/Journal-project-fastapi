import asyncio
import logging
import os
import signal

from app.db import db
from app.jobs.outbox import dispatch_pending_outbox_jobs


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def run_worker() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)
    stop_event = asyncio.Event()
    poll_seconds = max(1.0, float(os.getenv("EMAIL_OUTBOX_POLL_SECONDS", "2")))

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await db.connect()
    logger.info("Outbox relay connected to database")

    try:
        while not stop_event.is_set():
            dispatched = await dispatch_pending_outbox_jobs(source="relay")
            if dispatched:
                logger.info("Outbox relay dispatched %s jobs", dispatched)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except TimeoutError:
                continue
    finally:
        await db.disconnect()
        logger.info("Outbox relay shut down cleanly")


if __name__ == "__main__":
    asyncio.run(run_worker())
