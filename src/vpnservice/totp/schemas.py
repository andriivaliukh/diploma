from __future__ import annotations

from pydantic import BaseModel, Field


class TOTPVerifyRequest(BaseModel):
    """Request body for TOTP code verification."""

    totp_code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6-digit TOTP code from the authenticator app",
    )


class EnrollmentConfirmedResponse(BaseModel):
    """Response returned when TOTP enrollment is confirmed during registration."""

    success: bool = True
    message: str = "TOTP enrollment confirmed"


class AccessTokenResponse(BaseModel):
    """Response returned when TOTP verification completes the login flow."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
