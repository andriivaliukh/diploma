from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vpnservice.auth.schemas import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
from vpnservice.auth.service import login_user, register_user
from vpnservice.config import Settings, get_settings
from vpnservice.database import get_db

router = APIRouter()


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a new user",
    description=(
        "Creates a user account and generates a mandatory TOTP secret. "
        "The response includes QR code data and an intermediate auth_token "
        "which must be used to confirm TOTP enrollment via POST /totp/verify."
    ),
)
async def register(
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RegisterResponse:
    """Handle user registration and initial TOTP secret generation."""
    user, totp_uri, plain_secret, qr_base64, auth_token = await register_user(
        username=body.username,
        password=body.password,
        db=db,
        settings=settings,
    )
    return RegisterResponse(
        user_id=user.id,
        username=user.username,
        totp_uri=totp_uri,
        totp_secret=plain_secret,
        totp_qr_base64=qr_base64,
        auth_token=auth_token,
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate with username and password",
    description=(
        "Verifies credentials and returns a short-lived intermediate JWT "
        "(scope=totp_verify, 5 min TTL). "
        "The client must complete TOTP verification via POST /totp/verify."
    ),
)
async def login(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    """Handle password-based authentication and issue an intermediate token."""
    auth_token = await login_user(
        username=body.username,
        password=body.password,
        db=db,
        settings=settings,
    )
    return LoginResponse(auth_token=auth_token)
