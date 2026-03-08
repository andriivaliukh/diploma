from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from vpnservice.config import Settings


def create_intermediate_token(user_id: str, settings: Settings) -> str:
    """
    Create a short-lived JWT for the TOTP verification step.

    The token carries scope='totp_verify' and is valid only for the
    POST /api/v1/auth/totp/verify endpoint.
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "scope": "totp_verify",
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_intermediate_ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_access_token(user_id: str, is_admin: bool, settings: Settings) -> str:
    """
    Create a full-access JWT issued after successful TOTP verification.

    The token carries scope='full' and is valid for all authenticated endpoints.
    The is_admin claim is embedded to avoid extra DB lookups on every request.
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": user_id,
        "scope": "full",
        "is_admin": is_admin,
        "iat": now,
        "exp": now + timedelta(seconds=settings.jwt_access_ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, settings: Settings) -> dict:
    """
    Decode and validate a JWT token, returning the payload.

    Raises ValueError with a human-readable message on expiry or invalid signature.
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise ValueError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ValueError("Invalid token") from exc
