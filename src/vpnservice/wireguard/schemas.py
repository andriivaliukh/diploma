"""WireGuard data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PeerStats:
    """Statistics and metadata for a WireGuard peer.

    Attributes:
        public_key: Base64-encoded WireGuard public key of the peer.
        allowed_ips: CIDR range(s) allowed through this peer's tunnel.
        last_handshake: Time of the last successful handshake, or None if never.
        transfer_rx: Bytes received from this peer.
        transfer_tx: Bytes sent to this peer.
    """

    public_key: str
    allowed_ips: str
    last_handshake: datetime | None
    transfer_rx: int
    transfer_tx: int
