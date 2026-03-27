import asyncio
import logging
import os
import signal

from app.background_jobs.scheduler import shutdown_scheduler, start_scheduler
from app.db import db


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def run_worker() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    await db.connect()
    logger.info("Background worker connected to database")
    start_scheduler()
    logger.info("Background worker is running")

    try:
        await stop_event.wait()
    finally:
        shutdown_scheduler()
        await db.disconnect()
        logger.info("Background worker shut down cleanly")


if __name__ == "__main__":
    asyncio.run(run_worker())
