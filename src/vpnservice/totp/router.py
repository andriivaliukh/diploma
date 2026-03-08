from __future__ import annotations

from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vpnservice.auth.jwt import create_access_token
from vpnservice.config import Settings, get_settings
from vpnservice.database import get_db
from vpnservice.dependencies import get_intermediate_user
from vpnservice.models import User
from vpnservice.totp.schemas import (
    AccessTokenResponse,
    EnrollmentConfirmedResponse,
    TOTPVerifyRequest,
)
from vpnservice.totp.service import verify_totp_code

router = APIRouter()


@router.post(
    "/verify",
    response_model=Union[AccessTokenResponse, EnrollmentConfirmedResponse],
    summary="Verify a TOTP code",
    description=(
        "Verifies a 6-digit TOTP code from the authenticator app. "
        "Behaviour depends on the user's enrollment state:\n"
        "- **Not yet enrolled** (after registration): confirms enrollment, "
        "returns {success: true}.\n"
        "- **Already enrolled** (after login): issues a full-access JWT, "
        "returns {access_token, token_type, expires_in}."
    ),
)
async def verify_totp(
    body: TOTPVerifyRequest,
    user: Annotated[User, Depends(get_intermediate_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Union[AccessTokenResponse, EnrollmentConfirmedResponse]:
    """
    Handle TOTP verification for both enrollment confirmation and login 2FA.

    Uses the intermediate JWT (scope=totp_verify) for authentication.
    """
    result = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.totp_secret))
    )
    user_with_totp = result.scalar_one_or_none()

    if user_with_totp is None or user_with_totp.totp_secret is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No TOTP secret found for this user",
        )

    totp_secret = user_with_totp.totp_secret
    if not verify_totp_code(totp_secret.encrypted_secret, body.totp_code, settings):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code",
        )

    if not totp_secret.is_verified:
        totp_secret.is_verified = True
        await db.commit()
        return EnrollmentConfirmedResponse()

    access_token = create_access_token(
        user_id=user_with_totp.id,
        is_admin=user_with_totp.is_admin,
        settings=settings,
    )
    return AccessTokenResponse(
        access_token=access_token,
        expires_in=settings.jwt_access_ttl,
    )
