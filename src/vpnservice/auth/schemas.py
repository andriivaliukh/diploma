from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="3–50 characters, alphanumeric and underscores only",
    )
    password: str = Field(min_length=8, description="Minimum 8 characters")


class RegisterResponse(BaseModel):
    """
    Response returned after successful registration.

    Contains TOTP enrollment data — the client must scan the QR code (or manually
    enter totp_secret) and then confirm enrollment via POST /api/v1/auth/totp/verify
    using the included auth_token.
    """

    user_id: str
    username: str
    totp_uri: str
    totp_secret: str
    totp_qr_base64: str
    auth_token: str


class LoginRequest(BaseModel):
    """Request body for password-based login."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """
    Response after successful password verification.

    The auth_token is a short-lived intermediate JWT (scope=totp_verify, 5 min TTL).
    The client must complete the TOTP step via POST /api/v1/auth/totp/verify.
    """

    auth_token: str
    requires_totp: bool = True
    token_type: str = "bearer"
