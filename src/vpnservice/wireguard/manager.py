"""WireGuard interface manager using subprocess calls to wg and ip tools."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from vpnservice.config import Settings, get_settings
from vpnservice.wireguard.schemas import PeerStats

logger = logging.getLogger(__name__)


class WireGuardError(Exception):
    """Raised when a WireGuard operation fails."""


class WireGuardManager:
    """Manages the WireGuard interface and peer lifecycle.

    Wraps wg and ip CLI tools via asyncio subprocesses. The manager is
    a singleton — create one instance at startup and reuse it.

    Attributes:
        _settings: Application configuration.
        _server_public_key: Cached server public key (populated during initialize).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings: Settings = settings or get_settings()
        self._server_public_key: str = ""

    async def initialize(self) -> None:
        """Create and configure the wg0 interface if it does not already exist.

        Generates a server keypair on first run if the private key file is absent.
        Idempotent: safe to call multiple times.

        Raises:
            WireGuardError: If the interface cannot be created or configured.
        """
        private_key = await self._ensure_server_keypair()
        self._server_public_key = await self._derive_public_key(private_key)

        if not await self._interface_exists():
            await self._run("ip", "link", "add", self._settings.wg_interface, "type", "wireguard")
            logger.info("Created WireGuard interface %s", self._settings.wg_interface)

        await self._run("wg", "set", self._settings.wg_interface,
                        "private-key", self._settings.wg_private_key_path,
                        "listen-port", str(self._settings.wg_listen_port))

        server_ip = await self._current_server_address()
        if server_ip is None:
            import ipaddress
            net = ipaddress.ip_network(self._settings.wg_subnet)
            server_addr = f"{list(net.hosts())[0]}/{net.prefixlen}"
            await self._run("ip", "addr", "add", server_addr, "dev", self._settings.wg_interface)

        await self._run("ip", "link", "set", self._settings.wg_interface, "up")
        logger.info("WireGuard interface %s is up, public key: %s",
                    self._settings.wg_interface, self._server_public_key)

    async def add_peer(
        self,
        public_key: str,
        allowed_ips: str,
        preshared_key: str | None = None,
    ) -> None:
        """Add a peer to the WireGuard interface.

        Args:
            public_key: Base64-encoded WireGuard public key of the peer.
            allowed_ips: CIDR range assigned to this peer (e.g. '10.10.0.2/32').
            preshared_key: Optional pre-shared key for additional symmetric encryption.

        Raises:
            WireGuardError: If the wg set command fails.
        """
        args = ["wg", "set", self._settings.wg_interface,
                "peer", public_key,
                "allowed-ips", allowed_ips]

        if preshared_key:
            args += ["preshared-key", "/dev/stdin"]
            await self._run(*args, stdin_data=preshared_key)
        else:
            await self._run(*args)

        logger.info("Added WireGuard peer %s with allowed_ips=%s", public_key[:8], allowed_ips)

    async def remove_peer(self, public_key: str) -> None:
        """Remove a peer from the WireGuard interface.

        Args:
            public_key: Base64-encoded WireGuard public key of the peer to remove.

        Raises:
            WireGuardError: If the wg set command fails.
        """
        await self._run("wg", "set", self._settings.wg_interface, "peer", public_key, "remove")
        logger.info("Removed WireGuard peer %s", public_key[:8])

    async def get_peer_stats(self, public_key: str) -> PeerStats | None:
        """Get transfer and handshake statistics for a specific peer.

        Args:
            public_key: Base64-encoded WireGuard public key of the peer.

        Returns:
            PeerStats if the peer exists, None otherwise.
        """
        peers = await self.list_peers()
        return next((p for p in peers if p.public_key == public_key), None)

    async def list_peers(self) -> list[PeerStats]:
        """List all active peers with their transfer/handshake statistics.

        Returns:
            List of PeerStats, one per configured peer on the interface.
        """
        try:
            output = await self._run_capture("wg", "show", self._settings.wg_interface, "dump")
        except WireGuardError:
            return []

        return self._parse_dump_output(output)

    def get_server_public_key(self) -> str:
        """Return the server's WireGuard public key.

        Returns:
            Base64-encoded public key string. Empty string if not yet initialized.
        """
        return self._server_public_key

    def get_endpoint(self) -> str:
        """Return the server's public endpoint in host:port format.

        Returns:
            Endpoint string from configuration (e.g. 'vpn.example.com:51820').
        """
        return self._settings.wg_endpoint

    async def is_available(self) -> bool:
        """Check whether the WireGuard interface is up and responsive.

        Returns:
            True if the interface exists and wg show succeeds, False otherwise.
        """
        try:
            await self._run_capture("wg", "show", self._settings.wg_interface)
            return True
        except WireGuardError:
            return False

    async def _ensure_server_keypair(self) -> str:
        """Load or generate the server's WireGuard private key.

        Creates the key file with secure permissions (0600) on first run.

        Returns:
            Raw private key string.

        Raises:
            WireGuardError: If key generation fails.
        """
        key_path = Path(self._settings.wg_private_key_path)

        if key_path.exists():
            return key_path.read_text().strip()

        key_path.parent.mkdir(parents=True, exist_ok=True)
        private_key = await self._run_capture("wg", "genkey")
        key_path.write_text(private_key.strip() + "\n")
        os.chmod(key_path, 0o600)
        logger.info("Generated new WireGuard server private key at %s", key_path)
        return private_key.strip()

    async def _derive_public_key(self, private_key: str) -> str:
        """Derive the public key from a WireGuard private key.

        Args:
            private_key: Base64-encoded WireGuard private key.

        Returns:
            Base64-encoded public key.
        """
        proc = await asyncio.create_subprocess_exec(
            "wg", "pubkey",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=private_key.strip().encode())
        if proc.returncode != 0:
            raise WireGuardError(f"wg pubkey failed: {stderr.decode().strip()}")
        return stdout.decode().strip()

    async def _interface_exists(self) -> bool:
        """Check if the WireGuard network interface already exists."""
        try:
            await self._run_capture("ip", "link", "show", self._settings.wg_interface)
            return True
        except WireGuardError:
            return False

    async def _current_server_address(self) -> str | None:
        """Return the current IP address of the WireGuard interface, or None."""
        try:
            output = await self._run_capture(
                "ip", "-4", "addr", "show", self._settings.wg_interface
            )
            for line in output.splitlines():
                stripped = line.strip()
                if stripped.startswith("inet "):
                    return stripped.split()[1]
            return None
        except WireGuardError:
            return None

    async def _run(self, *args: str, stdin_data: str | None = None) -> None:
        """Execute a command and raise WireGuardError on non-zero exit.

        Args:
            *args: Command and arguments.
            stdin_data: Optional string to write to the process stdin.

        Raises:
            WireGuardError: If the process exits with a non-zero code.
        """
        stdin_flag = asyncio.subprocess.PIPE if stdin_data else None
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=stdin_flag,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        input_bytes = stdin_data.encode() if stdin_data else None
        _, stderr = await proc.communicate(input=input_bytes)
        if proc.returncode != 0:
            raise WireGuardError(
                f"Command {args[0]} failed (exit {proc.returncode}): {stderr.decode().strip()}"
            )

    async def _run_capture(self, *args: str) -> str:
        """Execute a command and return its stdout as a string.

        Args:
            *args: Command and arguments.

        Returns:
            Captured stdout.

        Raises:
            WireGuardError: If the process exits with a non-zero code.
        """
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise WireGuardError(
                f"Command {args[0]} failed (exit {proc.returncode}): {stderr.decode().strip()}"
            )
        return stdout.decode()

    def _parse_dump_output(self, output: str) -> list[PeerStats]:
        """Parse `wg show <interface> dump` output into PeerStats objects.

        The dump format is tab-separated:
        - Line 1 (interface): private-key  public-key  listen-port  fwmark
        - Lines 2+ (peers):   public-key  preshared-key  endpoint  allowed-ips
                               latest-handshake  transfer-rx  transfer-tx  persistent-keepalive

        Args:
            output: Raw stdout from `wg show <interface> dump`.

        Returns:
            List of PeerStats, one per peer line.
        """
        stats: list[PeerStats] = []
        lines = output.strip().splitlines()

        for line in lines[1:]:
            fields = line.split("\t")
            if len(fields) < 8:
                continue

            public_key = fields[0]
            allowed_ips = fields[3]
            handshake_ts = int(fields[4])
            transfer_rx = int(fields[5])
            transfer_tx = int(fields[6])

            last_handshake: datetime | None = None
            if handshake_ts > 0:
                last_handshake = datetime.fromtimestamp(handshake_ts, tz=timezone.utc)

            stats.append(PeerStats(
                public_key=public_key,
                allowed_ips=allowed_ips,
                last_handshake=last_handshake,
                transfer_rx=transfer_rx,
                transfer_tx=transfer_tx,
            ))

        return stats
