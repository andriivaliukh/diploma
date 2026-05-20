"""CLI entry point for vpncli.

Defines the Typer application and all top-level commands:
register, login, connect, disconnect, status, and sessions.
"""

import signal
import socket
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from vpncli.api_client import APIError, VPNAPIClient
from vpncli.auth import ensure_authenticated, login_flow, register_flow
from vpncli.config import clear_token, load_token
from vpncli.tunnel import (
    TunnelError,
    bring_down_tunnel,
    bring_up_tunnel,
    create_wg_config,
    generate_keypair,
    get_tunnel_status,
)


app = typer.Typer(
    name="vpncli",
    help="WireGuard VPN client with 2FA support.",
    no_args_is_help=True,
)
sessions_app = typer.Typer(help="Manage VPN sessions.")
app.add_typer(sessions_app, name="sessions")

console = Console()

_INSECURE_HELP = "Disable TLS certificate verification (for self-signed certs)."


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


@app.command()
def register(
    server: str = typer.Option(..., "--server", help="VPN server base URL."),
    username: str = typer.Option(..., "--username", help="Desired username."),
    password: Optional[str] = typer.Option(
        None, "--password",
        help="Skip interactive prompt; supply password directly. "
             "Visible in process table; intended for bench/test use only.",
    ),
    auto_totp: bool = typer.Option(
        False, "--auto-totp",
        help="Skip interactive TOTP prompt; compute first code from server-returned secret. "
             "Echoes 'TOTP_SECRET=<base32>' to stderr. Bench/test use only.",
    ),
    insecure: bool = typer.Option(False, "--insecure", help=_INSECURE_HELP),
) -> None:
    """Register a new user account and enroll TOTP.

    Prompts for a password (with confirmation), calls the server
    registration endpoint, displays the TOTP enrollment URI, then
    verifies the first TOTP code to confirm enrollment.
    """
    client = VPNAPIClient(verify_ssl=not insecure)
    try:
        register_flow(client, server.rstrip("/"), username,
                      password=password, auto_totp=auto_totp)
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[bold red]Unexpected error: {exc}[/bold red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


@app.command()
def login(
    server: str = typer.Option(..., "--server", help="VPN server base URL."),
    username: str = typer.Option(..., "--username", help="Username."),
    password: Optional[str] = typer.Option(
        None, "--password",
        help="Skip interactive prompt; supply password directly. "
             "Visible in process table; intended for bench/test use only.",
    ),
    totp_secret: Optional[str] = typer.Option(
        None, "--totp-secret",
        help="Skip interactive TOTP prompt; compute current code from this base32 secret. "
             "Bench/test use only.",
    ),
    insecure: bool = typer.Option(False, "--insecure", help=_INSECURE_HELP),
) -> None:
    """Log in and save an access token locally.

    Prompts for password and TOTP code, then stores the resulting
    access token in ~/.vpncli/tokens.json.
    """
    client = VPNAPIClient(verify_ssl=not insecure)
    try:
        login_flow(client, server.rstrip("/"), username,
                   password=password, totp_secret=totp_secret)
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[bold red]Unexpected error: {exc}[/bold red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------


@app.command()
def connect(
    server: str = typer.Option(..., "--server", help="VPN server base URL."),
    username: Optional[str] = typer.Option(None, "--username", help="Username (prompted if not cached)."),
    device_name: Optional[str] = typer.Option(None, "--device-name", help="Device name for this session."),
    insecure: bool = typer.Option(False, "--insecure", help=_INSECURE_HELP),
) -> None:
    """Connect to the VPN tunnel.

    Full connect flow:
    1. Check for a cached valid token; run login if none.
    2. Generate an ephemeral WireGuard keypair.
    3. Create a VPN session on the server.
    4. Write the WireGuard config and bring up the tunnel.
    5. Print connection info and wait for Ctrl+C or disconnect command.
    6. On exit: bring down the tunnel and revoke the session.
    """
    server = server.rstrip("/")
    client = VPNAPIClient(verify_ssl=not insecure)

    access_token = ensure_authenticated(client, server, username)

    resolved_device_name = device_name or f"{socket.gethostname()}-vpncli"

    console.print("Generating WireGuard keypair…")
    try:
        private_key, public_key = generate_keypair()
    except TunnelError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1)

    console.print("Creating VPN session…")
    try:
        session = client.create_session(
            server, access_token, resolved_device_name, public_key
        )
    except APIError as exc:
        if exc.status_code == 401:
            console.print("[bold red]Token expired. Run 'vpncli login' first.[/bold red]")
            clear_token(server)
        elif exc.status_code == 409:
            console.print(f"[bold red]Session conflict: {exc.detail}[/bold red]")
        elif exc.status_code == 503:
            console.print("[bold red]WireGuard interface unavailable on server.[/bold red]")
        else:
            console.print(f"[bold red]Failed to create session: {exc}[/bold red]")
        raise typer.Exit(1)

    session_id: str = session["session_id"]
    config_path: Optional[Path] = None

    def _teardown(revoke: bool = True) -> None:
        """Bring down the tunnel and optionally revoke the server session."""
        if config_path is not None and config_path.exists():
            console.print("\nBringing down tunnel…")
            try:
                bring_down_tunnel(config_path)
            except TunnelError as exc:
                console.print(f"[yellow]Warning: {exc}[/yellow]")

        if revoke:
            console.print("Revoking VPN session…")
            try:
                client.revoke_session(server, access_token, session_id)
                console.print("[bold green]Session revoked.[/bold green]")
            except APIError as exc:
                console.print(f"[yellow]Could not revoke session: {exc}[/yellow]")

    def _signal_handler(signum: int, frame: object) -> None:
        _teardown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    wg_config = create_wg_config(
        private_key=private_key,
        server_public_key=session["server_public_key"],
        endpoint=session["server_endpoint"],
        assigned_ip=session["assigned_ip"],
        dns_servers=session.get("dns_servers", []),
        allowed_ips=session.get("allowed_ips", ["0.0.0.0/0"]),
        keepalive_interval=session.get("keepalive_interval", 25),
    )

    console.print("Bringing up WireGuard tunnel…")
    try:
        config_path = bring_up_tunnel(wg_config)
    except TunnelError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        _teardown(revoke=True)
        raise typer.Exit(1)

    console.print(
        f"\n[bold green]Connected![/bold green]\n"
        f"  Assigned IP : [cyan]{session['assigned_ip']}[/cyan]\n"
        f"  Server      : [cyan]{session['server_endpoint']}[/cyan]\n"
        f"  Session ID  : {session_id}\n"
        f"  Expires at  : {session.get('expires_at', 'unknown')}\n"
        f"\nPress [bold]Ctrl+C[/bold] to disconnect."
    )

    signal.pause()


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


@app.command()
def disconnect(
    server: str = typer.Option(..., "--server", help="VPN server base URL."),
    session_id: str = typer.Option(..., "--session-id", help="Session UUID to revoke."),
    insecure: bool = typer.Option(False, "--insecure", help=_INSECURE_HELP),
) -> None:
    """Revoke a VPN session on the server.

    Use this to clean up a session when the 'connect' command cannot
    perform its own teardown (e.g., after a container restart).
    """
    server = server.rstrip("/")
    client = VPNAPIClient(verify_ssl=not insecure)

    access_token = load_token(server)
    if not access_token:
        console.print("[bold red]No valid token found. Run 'vpncli login' first.[/bold red]")
        raise typer.Exit(1)

    try:
        client.revoke_session(server, access_token, session_id)
        console.print(f"[bold green]Session {session_id} revoked.[/bold green]")
    except APIError as exc:
        if exc.status_code == 404:
            console.print(f"[bold red]Session not found: {session_id}[/bold red]")
        elif exc.status_code == 409:
            console.print("[yellow]Session was already expired or revoked.[/yellow]")
        else:
            console.print(f"[bold red]Failed to revoke session: {exc}[/bold red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    server: Optional[str] = typer.Option(None, "--server", help="Check token for this server URL."),
) -> None:
    """Show local token status and WireGuard tunnel state.

    Displays whether a valid token is cached for the given server and
    whether a vpncli WireGuard interface is currently active.
    """
    tunnel_up = get_tunnel_status()

    if server:
        server = server.rstrip("/")
        token = load_token(server)
        token_status = "[bold green]valid[/bold green]" if token else "[bold red]not found / expired[/bold red]"
        console.print(f"Token for {server}: {token_status}")
    else:
        console.print("(Use --server <url> to check token status for a specific server.)")

    tunnel_status = "[bold green]up[/bold green]" if tunnel_up else "[bold red]down[/bold red]"
    console.print(f"WireGuard tunnel : {tunnel_status}")


# ---------------------------------------------------------------------------
# sessions list / revoke
# ---------------------------------------------------------------------------


@sessions_app.command("list")
def sessions_list(
    server: str = typer.Option(..., "--server", help="VPN server base URL."),
    username: Optional[str] = typer.Option(None, "--username", help="Username (prompted if not cached)."),
    insecure: bool = typer.Option(False, "--insecure", help=_INSECURE_HELP),
) -> None:
    """List all VPN sessions for the current user."""
    server = server.rstrip("/")
    client = VPNAPIClient(verify_ssl=not insecure)
    access_token = ensure_authenticated(client, server, username)

    try:
        result = client.list_sessions(server, access_token)
    except APIError as exc:
        console.print(f"[bold red]Failed to list sessions: {exc}[/bold red]")
        raise typer.Exit(1)

    sessions = result.get("sessions", [])

    if not sessions:
        console.print("No sessions found.")
        return

    table = Table(title="VPN Sessions", show_header=True)
    table.add_column("Session ID", style="cyan")
    table.add_column("Device Name")
    table.add_column("Assigned IP", style="green")
    table.add_column("Status")
    table.add_column("Created At")
    table.add_column("Expires At")

    for s in sessions:
        status_color = "green" if s.get("status") == "active" else "red"
        table.add_row(
            s.get("session_id", ""),
            s.get("device_name", ""),
            s.get("assigned_ip", ""),
            f"[{status_color}]{s.get('status', '')}[/{status_color}]",
            s.get("created_at", ""),
            s.get("expires_at", ""),
        )

    console.print(table)


@sessions_app.command("revoke")
def sessions_revoke(
    server: str = typer.Option(..., "--server", help="VPN server base URL."),
    session_id: str = typer.Option(..., "--session-id", help="Session UUID to revoke."),
    username: Optional[str] = typer.Option(None, "--username", help="Username (prompted if not cached)."),
    insecure: bool = typer.Option(False, "--insecure", help=_INSECURE_HELP),
) -> None:
    """Revoke a specific VPN session by ID."""
    server = server.rstrip("/")
    client = VPNAPIClient(verify_ssl=not insecure)
    access_token = ensure_authenticated(client, server, username)

    try:
        client.revoke_session(server, access_token, session_id)
        console.print(f"[bold green]Session {session_id} revoked.[/bold green]")
    except APIError as exc:
        if exc.status_code == 404:
            console.print(f"[bold red]Session not found: {session_id}[/bold red]")
        elif exc.status_code == 409:
            console.print("[yellow]Session was already expired or revoked.[/yellow]")
        else:
            console.print(f"[bold red]Failed to revoke: {exc}[/bold red]")
        raise typer.Exit(1)
