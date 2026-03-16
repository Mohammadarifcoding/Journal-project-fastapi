from fastapi import APIRouter, HTTPException, Request, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from app.utils.limiter import limiter
from app.middleware.auth import auth_middleware
from app.ai.generate_summary import generate_summary
from app.db import db
import json

router = APIRouter()


class LogEntry(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    content: str = Field(..., min_length=10)
    tags: list[str] = Field(..., min_items=1)


async def analyze_log_background(data: LogEntry, logId: str):
    try:
        summary_result = await generate_summary(data)
        full_data = json.loads(summary_result.json())
        await db.aianalysis.update(
            where={"logId": logId},
            data={
                "summary": full_data.get("summary"),
                "key_points": full_data.get("key_points", []),
                "suggested_tags": full_data.get("suggested_tags", []),
                "learning_score": int(full_data.get("learning_score", 0)),
                "status": "completed",
            },
        )
    except Exception as e:
        print(f"Failed to analyze log {logId}: {e}")
        await db.aianalysis.update(where={"logId": logId}, data={"status": "failed"})


@router.post("/logs")
@limiter.limit("10/minute")
async def create_log(
    request: Request,
    log_data: LogEntry,
    background_tasks: BackgroundTasks,
    user=Depends(auth_middleware),
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
        await db.aianalysis.create(data={"logId": result.id, "status": "processing"})
        background_tasks.add_task(analyze_log_background, log_data, result.id)
        return {
            "message": "Log created successfully",
            "data": {
                "id": str(result.id),
                "title": log_doc["title"],
                "content": log_doc["content"],
                "tags": log_doc["tags"],
                "createdAt": result.createdAt,
                "ai_status": "processing",
            },
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


@router.delete("/logs/{log_id}")
@limiter.limit("20/minute")
async def delete_log(request: Request, log_id: str, user=Depends(auth_middleware)):
    try:
        log = await db.log.find_first(where={"id": log_id, "userId": user["id"]})
        if not log:
            raise HTTPException(status_code=404, detail="Log not found")
        await db.log.delete(where={"id": log_id})
        return {"message": "Log deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete log: {e}",
        )


@router.get("/logs/{log_id}/analysis")
@limiter.limit("20/minute")
async def get_log_analysis(
    request: Request, log_id: str, user=Depends(auth_middleware)
):
    try:
        log = await db.log.find_first(where={"id": log_id, "userId": user["id"]})
        if not log:
            raise HTTPException(status_code=404, detail="Log not found")
        analysis = await db.aianalysis.find_first(where={"logId": log_id})
        if not analysis:
            raise HTTPException(status_code=404, detail="Analysis not found")
        status_message_map = {
            "processing": "AI analysis is still in progress. Please check back later.",
            "completed": "AI analysis completed successfully.",
            "failed": "AI analysis failed. Please retry.",
        }
        message = status_message_map.get(analysis.status, "Unknown status")

        return {
            "status": analysis.status,
            "message": message,
            "data": (
                {
                    "summary": analysis.summary,
                    "key_points": analysis.key_points,
                    "suggested_tags": analysis.suggested_tags,
                    "learning_score": analysis.learning_score,
                }
                if analysis.status == "completed"
                else None
            ),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch analysis: {e}",
        )
