from jose import jwt, JWTError
from fastapi import APIRouter, HTTPException, Request
from app.db import db
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
import os
from app.jobs.outbox import create_registration_outbox_job, dispatch_outbox_job
from app.utils.security import (
    verify_password,
    create_access_token,
    hash_password,
    create_refresh_token,
)
from app.utils.limiter import limiter

router = APIRouter()
security = HTTPBearer()


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


@router.post("/auth/login")
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
        "data": {"userId": user.id},
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


@router.post("/auth/register")
@limiter.limit("5/minute")
async def register(request: Request, data: RegisterRequest):
    existing_user = await db.user.find_unique(where={"email": data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    try:
        hashed_password = hash_password(data.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    async with db.tx() as tx:
        user = await tx.user.create(
            data={"email": data.email, "password": hashed_password, "name": data.name}
        )
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token = create_refresh_token({"sub": str(user.id)})

        await tx.user.update(
            where={"email": data.email}, data={"refreshToken": refresh_token}
        )
        outbox_job_id = await create_registration_outbox_job(
            tx,
            user_id=str(user.id),
            email=user.email,
        )

    dispatched = await dispatch_outbox_job(outbox_job_id, source="api:register")
    return {
        "message": "User created successfully",
        "data": {"id": user.id, "email": user.email, "name": user.name},
        "access_token": access_token,
        "refresh_token": refresh_token,
        "background": {
            "registration_email": "queued" if dispatched else "pending_dispatch",
            "job_id": outbox_job_id,
        },
    }


@router.get("/auth/me")
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")

    token = credentials.credentials
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()

    SECRET_KEY = os.getenv("SECRET_KEY")
    ALGORITHM = os.getenv("ALGORITHM")

    if not SECRET_KEY or not ALGORITHM:
        raise RuntimeError("JWT configuration missing")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await db.user.find_unique(where={"id": str(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "data": {"id": user.id, "email": user.email, "name": user.name},
        "message": "User retrieved successfully",
    }
