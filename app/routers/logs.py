from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from app.utils.limiter import limiter
from app.middleware.auth import auth_middleware
from app.db import db

router = APIRouter()


class LogEntry(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    content: str = Field(..., min_length=10)
    tags: list[str] = Field(..., min_items=1)


@router.post("/logs")
@limiter.limit("10/minute")
async def create_log(
    request: Request, log_data: LogEntry, user=Depends(auth_middleware)
):
    try:
        log_doc = {
            "userId": user["id"],
            "title": log_data.title,
            "content": log_data.content,
            "tags": log_data.tags,
        }
        print("Creating log:", log_doc)
        result = await db.log.create(data=log_doc)
        return {
            "message": "Log created successfully",
            "data": {"id": str(result.id), **log_doc},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create log: {e}")


@router.get("/logs")
@limiter.limit("20/minute")
async def get_logs(request: Request, user=Depends(auth_middleware)):
    try:
        logs = await db.log.find_many(where={"userId": user["id"]})
        return {"data": logs, "message": "Logs fetched successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {e}")


@router.get("/logs/{log_id}")
@limiter.limit("20/minute")
async def get_log(request: Request, log_id: str, user=Depends(auth_middleware)):
    try:
        log = await db.log.find_first(where={"id": log_id, "userId": user["id"]})
        if not log:
            raise HTTPException(status_code=404, detail="Log not found")
        return {"data": log, "message": "Log fetched successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch logs: {e}",
        )
