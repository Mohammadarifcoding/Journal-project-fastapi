from fastapi import FastAPI
from pydantic import BaseModel
from enum import Enum
from typing import Dict, Optional
from slowapi import _rate_limit_exceeded_handler
from app.db import db
from app.utils.limiter import limiter
from slowapi.errors import RateLimitExceeded
from app.routers.users import router as users_router
from app.routers.logs import router as logs_router
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    print("Database connected!")
    yield
    await db.disconnect()
    print("Database disconnected!")


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/")
def read_root():
    return {"message": "Welcome to Ai Journal platform!"}


app.include_router(users_router, prefix="/api/v1", tags=["users"])
app.include_router(logs_router, prefix="/api/v1", tags=["logs"])
