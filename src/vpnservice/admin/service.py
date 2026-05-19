from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vpnservice.admin.schemas import (
    SessionAdminView,
    SessionListResponse,
    SessionRevokeResponse,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    UserAdminView,
    UserListResponse,
)
from vpnservice.config import Settings
from vpnservice.models import Device, SessionStatus, SystemSettings, TOTPSecret, User, VPNSession
from vpnservice.wireguard.manager import WireGuardManager

logger = logging.getLogger(__name__)


async def list_users(db: AsyncSession) -> UserListResponse:
    """
    Return all registered users with their TOTP enrollment status
    and active session count.
    """
    active_sessions_subq = (
        select(func.count(VPNSession.id))
        .where(
            and_(
                VPNSession.user_id == User.id,
                VPNSession.status == SessionStatus.active,
            )
        )
        .correlate(User)
        .scalar_subquery()
    )

    result = await db.execute(
        select(User, active_sessions_subq.label("active_sessions_count"))
        .options(selectinload(User.totp_secret))
        .order_by(User.created_at)
    )

    users = [
        UserAdminView(
            user_id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            is_active=user.is_active,
            totp_enrolled=(
                user.totp_secret.is_verified
                if user.totp_secret is not None
                else False
            ),
            created_at=user.created_at,
            active_sessions_count=active_count or 0,
        )
        for user, active_count in result.all()
    ]
    return UserListResponse(users=users)


async def list_all_sessions(db: AsyncSession) -> SessionListResponse:
    """Return all active VPN sessions across all users."""
    result = await db.execute(
        select(VPNSession, User, Device)
        .join(User, VPNSession.user_id == User.id)
        .join(Device, VPNSession.device_id == Device.id)
        .where(VPNSession.status == SessionStatus.active)
        .order_by(VPNSession.created_at.desc())
    )

    sessions = [
        SessionAdminView(
            session_id=session.id,
            user_id=user.id,
            username=user.username,
            device_name=device.name,
            assigned_ip=session.assigned_ip,
            status=session.status.value,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )
        for session, user, device in result.all()
    ]
    return SessionListResponse(sessions=sessions)


async def force_revoke_session(
    session_id: str,
    db: AsyncSession,
    wireguard_manager: WireGuardManager,
) -> SessionRevokeResponse:
    """
    Force-revoke a VPN session and remove the corresponding WireGuard peer.

    Raises:
        HTTPException 404 — session not found
        HTTPException 409 — session already expired or revoked
    """
    result = await db.execute(
        select(VPNSession)
        .where(VPNSession.id == session_id)
        .options(selectinload(VPNSession.device))
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    if session.status != SessionStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is already {session.status.value}",
        )

    # WireGuard requires root privileges — remove_peer is a no-op when the
    # WireGuard interface is unavailable (handled by WireGuardManager internally).
    await wireguard_manager.remove_peer(session.device.public_key)

    session.status = SessionStatus.revoked
    session.revoked_at = datetime.now(tz=timezone.utc)
    await db.commit()

    return SessionRevokeResponse(session_id=session.id)


async def get_settings(db: AsyncSession) -> SystemSettingsResponse:
    """
    Return the current system settings singleton.

    Creates the singleton with defaults if it does not yet exist.
    """
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.id == 1)
    )
    settings_row = result.scalar_one_or_none()

    if settings_row is None:
        settings_row = SystemSettings()
        db.add(settings_row)
        await db.commit()
        await db.refresh(settings_row)

    return SystemSettingsResponse(
        max_sessions_per_user=settings_row.max_sessions_per_user,
        session_ttl_hours=settings_row.session_ttl_hours,
    )


async def update_settings(
    update: SystemSettingsUpdateRequest,
    db: AsyncSession,
) -> SystemSettingsResponse:
    """
    Update system settings.

    Only provided (non-None) fields are changed. Fetches the singleton,
    creating it with defaults if absent.
    """
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.id == 1)
    )
    settings_row = result.scalar_one_or_none()

    if settings_row is None:
        settings_row = SystemSettings()
        db.add(settings_row)
        await db.flush()

    if update.max_sessions_per_user is not None:
        settings_row.max_sessions_per_user = update.max_sessions_per_user

    if update.session_ttl_hours is not None:
        settings_row.session_ttl_hours = update.session_ttl_hours

    await db.commit()
    await db.refresh(settings_row)

    return SystemSettingsResponse(
        max_sessions_per_user=settings_row.max_sessions_per_user,
        session_ttl_hours=settings_row.session_ttl_hours,
    )


async def seed_admin_user(settings: Settings) -> None:
    """
    Create the initial admin user from environment variables at startup.

    Reads VPN_ADMIN_USERNAME and VPN_ADMIN_PASSWORD from configuration.
    If those are set and no user with that username exists, the admin is
    created with a pre-generated TOTP secret. The TOTP URI and plain secret
    are printed to the log so the operator can scan the QR code with their
    authenticator app.

    The admin must complete TOTP enrollment by calling POST /api/v1/auth/login
    followed by POST /api/v1/auth/totp/verify on first login.
    """
    if not settings.admin_username or not settings.admin_password:
        return

    from vpnservice.auth.service import hash_password
    from vpnservice.database import get_session_factory
    from vpnservice.totp.service import generate_totp_secret

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(User).where(User.username == settings.admin_username)
        )
        if result.scalar_one_or_none() is not None:
            return

        admin = User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            is_admin=True,
        )
        db.add(admin)
        await db.flush()

        plain_secret, totp_uri, _qr_base64, encrypted_secret = generate_totp_secret(
            settings.admin_username, settings
        )
        totp_record = TOTPSecret(
            user_id=admin.id,
            encrypted_secret=encrypted_secret,
            is_verified=True,
        )
        db.add(totp_record)
        await db.commit()

        logger.warning(
            "Admin user '%s' created. Scan the TOTP URI with your authenticator "
            "app and complete enrollment via POST /api/v1/auth/totp/verify.",
            settings.admin_username,
        )
        logger.warning("TOTP provisioning URI: %s", totp_uri)
        logger.warning("TOTP secret (manual entry): %s", plain_secret)
