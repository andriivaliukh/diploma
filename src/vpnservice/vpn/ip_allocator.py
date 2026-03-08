"""IP address allocator for the WireGuard subnet pool."""

from __future__ import annotations

import ipaddress

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vpnservice.config import Settings
from vpnservice.models import SessionStatus, VPNSession


async def allocate_ip(db: AsyncSession, settings: Settings) -> str | None:
    """Assign the lowest available IP from the WireGuard subnet pool.

    The server always occupies the first host address (.1). Clients receive
    addresses .2 through .254 in ascending order.

    Args:
        db: Active database session used to query in-use addresses.
        settings: Application configuration containing the subnet definition.

    Returns:
        An IP address in CIDR notation (e.g. '10.10.0.2/32'), or None if the
        pool is exhausted.
    """
    subnet = ipaddress.ip_network(settings.wg_subnet)
    all_hosts = list(subnet.hosts())

    result = await db.execute(
        select(VPNSession.assigned_ip).where(VPNSession.status == SessionStatus.active)
    )
    in_use: set[str] = {row[0].split("/")[0] for row in result.all()}

    for host in all_hosts[1:]:
        if str(host) not in in_use:
            return f"{host}/32"

    return None
