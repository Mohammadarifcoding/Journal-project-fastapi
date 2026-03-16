from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import os


security = HTTPBearer()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")


async def auth_middleware(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authentication scheme")

    if not SECRET_KEY or not ALGORITHM:
        raise HTTPException(status_code=500, detail="JWT configuration missing")

    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": user_id}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
