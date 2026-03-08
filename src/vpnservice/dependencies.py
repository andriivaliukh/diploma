from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vpnservice.config import Settings, get_settings
from vpnservice.database import get_db
from vpnservice.models import User

_bearer_scheme = HTTPBearer()


def _decode_jwt(token: str, settings: Settings, required_scope: str) -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    if payload.get("scope") != required_scope:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token scope must be '{required_scope}'",
        )
    return payload


async def _get_user_from_token(
    payload: dict, db: AsyncSession
) -> User:
    """Load a user from the database using JWT payload."""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Validate a full-access JWT and return the user."""
    payload = _decode_jwt(credentials.credentials, settings, required_scope="full")
    return await _get_user_from_token(payload, db)


async def get_intermediate_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Validate a TOTP-verification intermediate JWT and return the user."""
    payload = _decode_jwt(
        credentials.credentials, settings, required_scope="totp_verify"
    )
    return await _get_user_from_token(payload, db)


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure the current user is an admin."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return user
