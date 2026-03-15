from unicodedata import name

from fastapi import APIRouter, HTTPException, Request
from app.db import db
from pydantic import BaseModel
from enum import Enum, unique
from typing import Dict, Optional
from app.utils.security import (
    verify_password,
    create_access_token,
    hash_password,
    create_refresh_token,
)
from app.utils.limiter import limiter

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str


@router.get("/users")
async def get_users():
    return {"data": []}


@router.post("/login")
@limiter.limit("5/minute")  # Slightly higher for real users
async def login(request: Request, data: LoginRequest):
    user = await db.user.find_unique(where={"email": data.email})

    if not user or not verify_password(data.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    await db.user.update(
        where={"email": data.email}, data={"refreshToken": refresh_token}
    )

    return {
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest):
    existing_user = await db.user.find_unique(where={"email": data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        hashed_password = hash_password(data.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    user = await db.user.create(
        data={"email": data.email, "password": hashed_password, "name": data.name}
    )
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    await db.user.update(
        where={"email": data.email}, data={"refreshToken": refresh_token}
    )
    return {
        "message": "User created successfully",
        "data": {"id": user.id, "email": user.email, "name": user.name},
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
