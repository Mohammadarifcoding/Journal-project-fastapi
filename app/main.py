from fastapi import FastAPI
from pydantic import BaseModel
from enum import Enum
from typing import Dict, Optional
from .router import router

app = FastAPI()


class Event(BaseModel):
    event_type: str
    user_id: int
    metadata: Optional[Dict] = None


class ModelName(str, Enum):
    alexnet = "alexnet"
    resnet = "resnet"
    lenet = "lenet"


@app.get("/")
def read_root():
    return {"message": "Hello World!"}


@app.get("/events/{item_id}")
def handle_event(
    item_id: ModelName,
    # data: Event,
) -> dict:
    print(item_id)

    # This is where you implement the AI logic to handle the event

    # Return acceptance response
    return {"item_id": item_id}


@app.get("/users/me")
async def read_user_me():
    return {"user_id": "the current user"}


@app.get("/users/{user_id}")
async def read_user(user_id: str):
    return {"user_id": user_id}


@app.get("/files/{file_path:path}")
async def read_file(file_path: str):
    return {"file_path": file_path}


# app.include_router(router)
