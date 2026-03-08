from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from vpnservice.admin.schemas import (
    SessionListResponse,
    SessionRevokeResponse,
    SystemSettingsResponse,
    SystemSettingsUpdateRequest,
    UserListResponse,
)
from vpnservice.admin.service import (
    force_revoke_session,
    get_settings,
    list_all_sessions,
    list_users,
    update_settings,
)
from vpnservice.database import get_db
from vpnservice.dependencies import require_admin
from vpnservice.models import User
from vpnservice.vpn.router import get_wg_manager
from vpnservice.wireguard.manager import WireGuardManager

router = APIRouter()


@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List all users",
    description="Returns all registered users with TOTP enrollment status and active session count.",
)
async def admin_list_users(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserListResponse:
    """Return all users. Requires admin privileges."""
    return await list_users(db)


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List all active VPN sessions",
    description="Returns all currently active VPN sessions across all users.",
)
async def admin_list_sessions(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SessionListResponse:
    """Return all active sessions. Requires admin privileges."""
    return await list_all_sessions(db)


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionRevokeResponse,
    summary="Force-revoke a VPN session",
    description=(
        "Immediately revokes any user's VPN session and removes "
        "the corresponding WireGuard peer from the server."
    ),
)
async def admin_revoke_session(
    session_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    wg_manager: Annotated[WireGuardManager, Depends(get_wg_manager)],
) -> SessionRevokeResponse:
    """Force-revoke a session by ID. Requires admin privileges."""
    return await force_revoke_session(
        session_id=session_id,
        db=db,
        wireguard_manager=wg_manager,
    )


@router.get(
    "/settings",
    response_model=SystemSettingsResponse,
    summary="Get system settings",
    description="Returns the current system-wide VPN settings.",
)
async def admin_get_settings(
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemSettingsResponse:
    """Return current system settings. Requires admin privileges."""
    return await get_settings(db)


@router.put(
    "/settings",
    response_model=SystemSettingsResponse,
    summary="Update system settings",
    description=(
        "Updates system-wide VPN settings. All fields are optional — "
        "only provided fields are changed."
    ),
)
async def admin_update_settings(
    body: SystemSettingsUpdateRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SystemSettingsResponse:
    """Update system settings. Requires admin privileges."""
    return await update_settings(update=body, db=db)
