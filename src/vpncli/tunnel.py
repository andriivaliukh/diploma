"""WireGuard tunnel management for the CLI client.

Generates ephemeral client keypairs, produces WireGuard configuration
files, and controls tunnel lifecycle via wg-quick.

# WireGuard requires root privileges and the NET_ADMIN capability.
"""

import secrets
import subprocess
from pathlib import Path
from typing import Optional


class TunnelError(Exception):
    """Raised when a WireGuard operation fails."""


def generate_keypair() -> tuple[str, str]:
    """Generate an ephemeral WireGuard private/public key pair.

    Calls the 'wg genkey' and 'wg pubkey' command-line tools, which
    must be installed (provided by wireguard-tools).

    Returns:
        A (private_key, public_key) tuple of base64-encoded strings.

    Raises:
        TunnelError: If the wg binary is not found or returns an error.
    """
    try:
        genkey_result = subprocess.run(
            ["wg", "genkey"],
            capture_output=True,
            text=True,
            check=True,
        )
        private_key = genkey_result.stdout.strip()

        pubkey_result = subprocess.run(
            ["wg", "pubkey"],
            input=private_key,
            capture_output=True,
            text=True,
            check=True,
        )
        public_key = pubkey_result.stdout.strip()
    except FileNotFoundError as exc:
        raise TunnelError(
            "wireguard-tools not found. Install wireguard-tools to use the tunnel."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise TunnelError(
            f"Failed to generate WireGuard keypair: {exc.stderr.strip()}"
        ) from exc

    return private_key, public_key


def create_wg_config(
    private_key: str,
    server_public_key: str,
    endpoint: str,
    assigned_ip: str,
    dns_servers: list[str],
    allowed_ips: list[str],
    keepalive_interval: int = 25,
) -> str:
    """Render a wg-quick compatible configuration file as a string.

    Args:
        private_key: Client's WireGuard private key (base64).
        server_public_key: Server's WireGuard public key (base64).
        endpoint: Server's WireGuard endpoint in host:port format.
        assigned_ip: IP address/prefix assigned to this client, e.g. 10.10.0.2/32.
        dns_servers: List of DNS server addresses to configure.
        allowed_ips: List of IP prefixes to route through the tunnel.
        keepalive_interval: Persistent keepalive interval in seconds.

    Returns:
        The wg-quick configuration file content as a string.
    """
    dns_line = ", ".join(dns_servers) if dns_servers else ""
    allowed_ips_line = ", ".join(allowed_ips) if allowed_ips else "0.0.0.0/0"

    config_lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {assigned_ip}",
    ]

    if dns_line:
        config_lines.append(f"DNS = {dns_line}")

    config_lines += [
        "",
        "[Peer]",
        f"PublicKey = {server_public_key}",
        f"Endpoint = {endpoint}",
        f"AllowedIPs = {allowed_ips_line}",
        f"PersistentKeepalive = {keepalive_interval}",
    ]

    return "\n".join(config_lines) + "\n"


def bring_up_tunnel(config_content: str) -> Path:
    """Write a WireGuard config to /etc/wireguard and bring up the tunnel.

    The config file is NOT deleted by this function — the caller is
    responsible for cleanup (and for calling bring_down_tunnel first).

    Args:
        config_content: The wg-quick configuration file content.

    Returns:
        Path to the config file in /etc/wireguard (needed for bring_down_tunnel).

    Raises:
        TunnelError: If wg-quick fails to bring up the interface.
    """
    iface = f"vpncli-{secrets.token_hex(3)}"
    config_dir = Path("/etc/wireguard")
    config_dir.mkdir(mode=0o700, exist_ok=True)
    config_path = config_dir / f"{iface}.conf"
    config_path.write_text(config_content)
    config_path.chmod(0o600)

    try:
        subprocess.run(
            ["wg-quick", "up", str(config_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        config_path.unlink(missing_ok=True)
        raise TunnelError(
            "wg-quick not found. Install wireguard-tools."
        ) from exc
    except subprocess.CalledProcessError as exc:
        config_path.unlink(missing_ok=True)
        raise TunnelError(
            f"wg-quick up failed: {exc.stderr.strip()}"
        ) from exc

    return config_path


def bring_down_tunnel(config_path: Path) -> None:
    """Bring down the WireGuard tunnel and delete the config file.

    Args:
        config_path: Path to the wg-quick configuration file used to
            bring the tunnel up.

    Raises:
        TunnelError: If wg-quick down fails (the config file is still
            deleted to avoid leaking the private key on disk).
    """
    error: Optional[str] = None
    try:
        subprocess.run(
            ["wg-quick", "down", str(config_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        error = "wg-quick not found — tunnel may still be up."
    except subprocess.CalledProcessError as exc:
        error = f"wg-quick down failed: {exc.stderr.strip()}"
    finally:
        config_path.unlink(missing_ok=True)

    if error:
        raise TunnelError(error)


def get_tunnel_status(config_path: Optional[Path] = None) -> bool:
    """Check whether a WireGuard interface managed by wg-quick is active.

    Looks for any 'vpncli-' prefixed interface via 'wg show'.

    Args:
        config_path: Optional path to the config file. If provided, the
            interface name is derived from the filename stem; otherwise
            any vpncli interface presence is checked.

    Returns:
        True if the interface is up, False otherwise.
    """
    try:
        result = subprocess.run(
            ["wg", "show", "interfaces"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

    interfaces = result.stdout.strip().split()

    if config_path is not None:
        iface_name = config_path.stem
        return iface_name in interfaces

    return any(iface.startswith("vpncli-") for iface in interfaces)
