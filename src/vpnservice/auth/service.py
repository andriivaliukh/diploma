from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vpnservice.auth.jwt import create_intermediate_token
from vpnservice.config import Settings
from vpnservice.models import TOTPSecret, User
from vpnservice.totp.service import generate_totp_secret

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except VerifyMismatchError:
        return False


async def register_user(
    username: str,
    password: str,
    db: AsyncSession,
    settings: Settings,
) -> tuple[User, str, str, str, str]:
    """
    Register a new user and generate their mandatory TOTP secret.

    Returns a 5-tuple of (user, totp_uri, plain_totp_secret, qr_base64, auth_token).
    The auth_token is an intermediate JWT the client must use to confirm enrollment
    via POST /api/v1/auth/totp/verify.

    Raises HTTPException 409 if the username is already taken.
    """
    result = await db.execute(select(User).where(User.username == username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    await db.flush()

    plain_secret, totp_uri, qr_base64, encrypted_secret = generate_totp_secret(
        username, settings
    )
    totp_record = TOTPSecret(
        user_id=user.id,
        encrypted_secret=encrypted_secret,
        is_verified=False,
    )
    db.add(totp_record)
    await db.commit()
    await db.refresh(user)

    auth_token = create_intermediate_token(user.id, settings)
    return user, totp_uri, plain_secret, qr_base64, auth_token


async def login_user(
    username: str,
    password: str,
    db: AsyncSession,
    settings: Settings,
) -> str:
    """
    Validate credentials and return an intermediate JWT for the TOTP step.

    Raises:
        HTTPException 401 — invalid credentials or inactive account
        HTTPException 403 — no TOTP secret set up (enrollment never started)
    """
    result = await db.execute(
        select(User)
        .where(User.username == username)
        .options(selectinload(User.totp_secret))
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive",
        )

    if user.totp_secret is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TOTP not yet enrolled. Complete registration first.",
        )

    if not user.totp_secret.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TOTP enrollment not confirmed.",
        )

    return create_intermediate_token(user.id, settings)
