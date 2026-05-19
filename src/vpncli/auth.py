"""Interactive authentication flows for the CLI client.

Handles the full register and login sequences, including prompting the
user for passwords and TOTP codes and persisting the resulting token.
"""

import getpass
from datetime import datetime, timedelta, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from vpncli.api_client import APIError, VPNAPIClient
from vpncli.config import load_token, save_token


console = Console()


def _prompt_password(prompt: str = "Password") -> str:
    """Prompt the user for a password without echoing input.

    Args:
        prompt: The label shown to the user.

    Returns:
        The entered password string.
    """
    return getpass.getpass(f"{prompt}: ")


def _prompt_totp() -> str:
    """Prompt the user for a 6-digit TOTP code.

    Returns:
        The entered TOTP code string.
    """
    return typer.prompt("Enter 6-digit TOTP code")


def register_flow(
    client: VPNAPIClient,
    server: str,
    username: str,
) -> None:
    """Run the interactive user registration flow.

    Steps:
    1. Prompt for password (with confirmation).
    2. Call the register API endpoint.
    3. Display the TOTP enrollment URI for the authenticator app.
    4. Perform a login to obtain an intermediate auth token.
    5. Prompt for TOTP code and verify enrollment.

    Args:
        client: A configured VPNAPIClient instance.
        server: Base URL of the VPN server.
        username: Desired username for the new account.

    Raises:
        typer.Exit: On unrecoverable errors (bad input, server errors).
    """
    password = _prompt_password("Password")
    password_confirm = _prompt_password("Confirm password")

    if password != password_confirm:
        console.print("[bold red]Passwords do not match.[/bold red]")
        raise typer.Exit(1)

    console.print(f"Registering user [bold]{username}[/bold] on {server}…")

    try:
        result = client.register(server, username, password)
    except APIError as exc:
        if exc.status_code == 409:
            console.print(f"[bold red]Username '{username}' is already taken.[/bold red]")
        elif exc.status_code == 422:
            console.print(f"[bold red]Validation error: {exc.detail}[/bold red]")
        else:
            console.print(f"[bold red]Registration failed: {exc}[/bold red]")
        raise typer.Exit(1)

    totp_uri: str = result["totp_uri"]
    totp_secret: str = result["totp_secret"]
    auth_token: str = result["auth_token"]

    console.print(
        Panel(
            Text.from_markup(
                "[bold green]Account created![/bold green]\n\n"
                "Scan this URI in your authenticator app:\n\n"
                f"[cyan]{totp_uri}[/cyan]\n\n"
                "Or enter the secret manually:\n"
                f"[yellow]{totp_secret}[/yellow]"
            ),
            title="TOTP Enrollment",
            border_style="green",
        )
    )

    totp_code = _prompt_totp()

    try:
        client.verify_totp(server, auth_token, totp_code)
        console.print("[bold green]TOTP enrollment confirmed. You can now use 'vpncli login'.[/bold green]")
    except APIError as exc:
        if exc.status_code == 400:
            console.print("[bold red]Invalid TOTP code. Run 'vpncli login' to try again.[/bold red]")
        else:
            console.print(f"[bold red]TOTP verification failed: {exc}[/bold red]")
        raise typer.Exit(1)


def login_flow(
    client: VPNAPIClient,
    server: str,
    username: str,
) -> str:
    """Run the interactive login flow and return a valid access token.

    Steps:
    1. Prompt for password.
    2. Call the login API endpoint to obtain an intermediate auth token.
    3. Prompt for TOTP code.
    4. Verify TOTP to obtain a full-access token.
    5. Persist the token to ~/.vpncli/tokens.json.

    Args:
        client: A configured VPNAPIClient instance.
        server: Base URL of the VPN server.
        username: The account username.

    Returns:
        The full-access JWT string.

    Raises:
        typer.Exit: On authentication failures.
    """
    password = _prompt_password()

    console.print(f"Logging in as [bold]{username}[/bold] on {server}…")

    try:
        login_result = client.login(server, username, password)
    except APIError as exc:
        if exc.status_code == 401:
            console.print("[bold red]Invalid username or password.[/bold red]")
        elif exc.status_code == 403:
            console.print("[bold red]TOTP not enrolled. Please register first.[/bold red]")
        else:
            console.print(f"[bold red]Login failed: {exc}[/bold red]")
        raise typer.Exit(1)

    auth_token: str = login_result["auth_token"]
    totp_code = _prompt_totp()

    try:
        verify_result = client.verify_totp(server, auth_token, totp_code)
    except APIError as exc:
        if exc.status_code == 400:
            console.print("[bold red]Invalid TOTP code.[/bold red]")
        elif exc.status_code == 401:
            console.print("[bold red]Auth token expired. Please log in again.[/bold red]")
        else:
            console.print(f"[bold red]TOTP verification failed: {exc}[/bold red]")
        raise typer.Exit(1)

    access_token: str = verify_result["access_token"]
    expires_in: int = verify_result.get("expires_in", 86400)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    save_token(server, access_token, expires_at)
    console.print("[bold green]Login successful. Token saved.[/bold green]")

    return access_token


def ensure_authenticated(
    client: VPNAPIClient,
    server: str,
    username: Optional[str],
) -> str:
    """Return a valid access token, running the login flow if necessary.

    Checks the local token store first. If no valid token is found,
    prompts the user for credentials and runs the full login flow.

    Args:
        client: A configured VPNAPIClient instance.
        server: Base URL of the VPN server.
        username: Username to use when a login flow is needed. If None,
            the user is prompted to provide one.

    Returns:
        A valid full-access JWT string.

    Raises:
        typer.Exit: If login fails.
    """
    token = load_token(server)
    if token:
        return token

    if username is None:
        username = typer.prompt("Username")

    return login_flow(client, server, username)
