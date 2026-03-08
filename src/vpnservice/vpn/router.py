"""FastAPI router for VPN session and device endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from vpnservice import __version__
from vpnservice.config import Settings, get_settings
from vpnservice.database import get_db
from vpnservice.dependencies import get_current_user
from vpnservice.models import User
from vpnservice.vpn import schemas
from vpnservice.vpn import service as vpn_service
from vpnservice.wireguard.manager import WireGuardManager

router = APIRouter()

_wg_manager: WireGuardManager | None = None


def set_wg_manager(manager: WireGuardManager) -> None:
    """Register the WireGuard manager instance for use by route handlers.

    Called once during application startup (lifespan).

    Args:
        manager: Initialized WireGuardManager instance.
    """
    global _wg_manager
    _wg_manager = manager


def get_wg_manager() -> WireGuardManager:
    """FastAPI dependency that returns the shared WireGuard manager.

    Returns:
        The application-wide WireGuardManager instance.
    """
    if _wg_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WireGuard manager not initialized.",
        )
    return _wg_manager


@router.post(
    "/sessions",
    response_model=schemas.SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new VPN session",
)
async def create_session(
    body: schemas.SessionCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    wg_manager: WireGuardManager = Depends(get_wg_manager),
) -> schemas.SessionCreateResponse:
    """Create a new VPN session and register the client as a WireGuard peer.

    Requires a full-access JWT (2FA completed). The client must supply its own
    WireGuard public key — the private key never leaves the client.

    Args:
        body: Device name and client public key.
        user: Authenticated user from JWT dependency.
        db: Database session.
        settings: Application settings.
        wg_manager: WireGuard manager dependency.

    Returns:
        Tunnel configuration the client needs to bring up the WireGuard interface.
    """
    return await vpn_service.create_session(
        user=user,
        device_name=body.device_name,
        client_public_key=body.client_public_key,
        db=db,
        settings=settings,
        wg_manager=wg_manager,
    )


@router.get(
    "/sessions",
    response_model=schemas.SessionListResponse,
    summary="List user's VPN sessions",
)
async def list_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    wg_manager: WireGuardManager = Depends(get_wg_manager),
) -> schemas.SessionListResponse:
    """List all VPN sessions for the authenticated user.

    Includes live WireGuard handshake times where available.

    Args:
        user: Authenticated user from JWT dependency.
        db: Database session.
        wg_manager: WireGuard manager dependency.

    Returns:
        All sessions for the user, newest first.
    """
    return await vpn_service.list_sessions(user=user, db=db, wg_manager=wg_manager)


@router.get(
    "/sessions/{session_id}",
    response_model=schemas.SessionDetailResponse,
    summary="Get session details",
)
async def get_session(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    wg_manager: WireGuardManager = Depends(get_wg_manager),
) -> schemas.SessionDetailResponse:
    """Get detailed information for a specific VPN session.

    Includes live transfer statistics from WireGuard where available.

    Args:
        session_id: UUID of the session to retrieve.
        user: Authenticated user from JWT dependency.
        db: Database session.
        wg_manager: WireGuard manager dependency.

    Returns:
        Session details including transfer bytes and last handshake time.
    """
    return await vpn_service.get_session(
        user=user, session_id=session_id, db=db, wg_manager=wg_manager
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=schemas.SessionRevokeResponse,
    summary="Revoke a VPN session",
)
async def revoke_session(
    session_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    wg_manager: WireGuardManager = Depends(get_wg_manager),
) -> schemas.SessionRevokeResponse:
    """Revoke a VPN session, removing the associated WireGuard peer.

    Only the session owner can revoke their own sessions.

    Args:
        session_id: UUID of the session to revoke.
        user: Authenticated user from JWT dependency.
        db: Database session.
        wg_manager: WireGuard manager dependency.

    Returns:
        Confirmation with session_id and status 'revoked'.
    """
    return await vpn_service.revoke_session(
        user=user, session_id=session_id, db=db, wg_manager=wg_manager
    )


health_router = APIRouter()


@health_router.get(
    "/health",
    response_model=schemas.HealthResponse,
    summary="Service health check",
    tags=["health"],
)
async def health_check(
    wg_manager: WireGuardManager = Depends(get_wg_manager),
) -> schemas.HealthResponse:
    """Return service health status including WireGuard interface state.

    Unauthenticated endpoint, safe to call from monitoring systems.

    Args:
        wg_manager: WireGuard manager dependency.

    Returns:
        Health status with WireGuard availability and application version.
    """
    wg_state = "up" if await wg_manager.is_available() else "down"
    return schemas.HealthResponse(
        status="healthy",
        wireguard=wg_state,
        version=__version__,
    )


devices_router = APIRouter()


@devices_router.get(
    "",
    response_model=schemas.DeviceListResponse,
    summary="List user's devices",
)
async def list_devices(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> schemas.DeviceListResponse:
    """List all devices registered by the authenticated user.

    Args:
        user: Authenticated user from JWT dependency.
        db: Database session.

    Returns:
        All devices belonging to the user, newest first.
    """
    return await vpn_service.list_devices(user=user, db=db)
