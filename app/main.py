import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.background_jobs.scheduler import (
    should_run_scheduler_in_api,
    shutdown_scheduler,
    start_scheduler,
)
from app.db import db
from app.routers.users import router as users_router
from app.routers.logs import router as logs_router
from app.utils.limiter import limiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    logger.info("Database connected")

    scheduler_running = False
    if should_run_scheduler_in_api():
        start_scheduler()
        scheduler_running = True

    try:
        yield
    finally:
        if scheduler_running:
            shutdown_scheduler()
        await db.disconnect()
        logger.info("Database disconnected")


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/")
def read_root():
    return {"message": "Welcome to Ai Journal platform!"}


app.include_router(users_router, prefix="/api/v1", tags=["users"])
app.include_router(logs_router, prefix="/api/v1", tags=["logs"])
