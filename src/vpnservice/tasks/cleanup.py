"""Background task for cleaning up expired VPN sessions."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vpnservice.database import get_session_factory
from vpnservice.models import Device, SessionStatus, VPNSession
from vpnservice.wireguard.manager import WireGuardError, WireGuardManager

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL_SECONDS = 60


async def _expire_session(
    session: VPNSession,
    device: Device,
    db: AsyncSession,
    wg_manager: WireGuardManager,
) -> None:
    """Mark a single session as expired and remove its WireGuard peer.

    Args:
        session: The VPNSession record to expire.
        device: The Device associated with the session (holds the public key).
        db: Active database session for the update.
        wg_manager: WireGuard manager used to remove the peer.
    """
    try:
        await wg_manager.remove_peer(device.public_key)
    except WireGuardError as exc:
        logger.warning(
            "Could not remove expired peer %s (session %s): %s",
            device.public_key[:8],
            session.id,
            exc,
        )

    session.status = SessionStatus.expired
    logger.info(
        "Expired session %s for device %s (expired at %s)",
        session.id,
        device.name,
        session.expires_at.isoformat(),
    )


async def run_cleanup_cycle(wg_manager: WireGuardManager) -> int:
    """Scan for expired sessions, remove their peers, and mark them expired.

    Args:
        wg_manager: WireGuard manager used to remove peers.

    Returns:
        Number of sessions that were expired in this cycle.
    """
    factory = get_session_factory()
    async with factory() as db:
        now = datetime.now(tz=timezone.utc)

        result = await db.execute(
            select(VPNSession, Device)
            .join(Device, VPNSession.device_id == Device.id)
            .where(
                VPNSession.status == SessionStatus.active,
                VPNSession.expires_at < now,
            )
        )
        expired_rows = result.all()

        if not expired_rows:
            return 0

        for vpn_session, device in expired_rows:
            await _expire_session(vpn_session, device, db, wg_manager)

        await db.commit()
        logger.info("Cleanup cycle: expired %d session(s)", len(expired_rows))
        return len(expired_rows)


async def session_cleanup_loop(wg_manager: WireGuardManager) -> None:
    """Run the session cleanup task in an infinite loop.

    Sleeps for CLEANUP_INTERVAL_SECONDS between cycles. Exceptions within a
    single cycle are caught and logged — the loop continues regardless.

    Args:
        wg_manager: WireGuard manager passed to each cleanup cycle.
    """
    logger.info(
        "Session cleanup task started (interval=%ds)", _CLEANUP_INTERVAL_SECONDS
    )
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            await run_cleanup_cycle(wg_manager)
        except Exception as exc:
            logger.error("Session cleanup cycle failed: %s", exc, exc_info=True)


def start_cleanup_task(wg_manager: WireGuardManager) -> asyncio.Task:
    """Schedule the session cleanup loop as an asyncio background task.

    Should be called during FastAPI lifespan startup after the WireGuard
    manager has been initialized.

    Args:
        wg_manager: Initialized WireGuard manager to pass to the cleanup loop.

    Returns:
        The asyncio.Task for the running cleanup loop.
    """
    return asyncio.create_task(
        session_cleanup_loop(wg_manager),
        name="session-cleanup",
    )
