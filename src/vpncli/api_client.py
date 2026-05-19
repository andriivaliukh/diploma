"""HTTP client for the VPN service REST API.

Wraps all server endpoints in typed methods, handling transport errors,
HTTP error codes, and JSON parsing failures uniformly.
"""

from typing import Any, Optional

import httpx


class APIError(Exception):
    """Raised when the server returns an unexpected HTTP status code.

    Attributes:
        status_code: The HTTP status code returned by the server.
        detail: Human-readable error detail from the response body.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


def _raise_for_status(response: httpx.Response) -> None:
    """Raise APIError for non-2xx responses with a useful message.

    Args:
        response: The httpx response to inspect.

    Raises:
        APIError: If the response status code indicates an error.
    """
    if response.is_success:
        return

    try:
        body = response.json()
        detail = body.get("detail", response.text)
    except Exception:
        detail = response.text or response.reason_phrase

    raise APIError(response.status_code, str(detail))


class VPNAPIClient:
    """Synchronous HTTP client for all VPN service API endpoints.

    Args:
        verify_ssl: Whether to verify TLS certificates. Set to False
            only for development/self-signed certificate environments.
    """

    def __init__(self, verify_ssl: bool = True) -> None:
        self._verify_ssl = verify_ssl

    def _client(self) -> httpx.Client:
        """Create a configured httpx client."""
        return httpx.Client(verify=self._verify_ssl, timeout=30.0)

    def _auth_headers(self, token: str) -> dict[str, str]:
        """Build Authorization header dict for a Bearer token."""
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Auth endpoints
    # ------------------------------------------------------------------

    def register(
        self, server: str, username: str, password: str
    ) -> dict[str, Any]:
        """Register a new user account.

        Args:
            server: Base URL of the VPN server (e.g. https://vpn.example.com).
            username: Desired username (3-50 chars, alphanumeric + underscore).
            password: Password (min 8 chars).

        Returns:
            Dict with user_id, username, totp_uri, totp_secret, totp_qr_base64, auth_token.

        Raises:
            APIError: On 409 (username taken), 422 (validation), or other errors.
            httpx.ConnectError: If the server is unreachable.
        """
        with self._client() as client:
            response = client.post(
                f"{server}/api/v1/auth/register",
                json={"username": username, "password": password},
            )
        _raise_for_status(response)
        return response.json()

    def login(
        self, server: str, username: str, password: str
    ) -> dict[str, Any]:
        """Authenticate with username and password.

        Returns an intermediate auth token that must be exchanged for a full
        access token by verifying the TOTP code.

        Args:
            server: Base URL of the VPN server.
            username: Registered username.
            password: Account password.

        Returns:
            Dict with auth_token, requires_totp, token_type.

        Raises:
            APIError: On 401 (invalid credentials), 403 (TOTP not enrolled).
            httpx.ConnectError: If the server is unreachable.
        """
        with self._client() as client:
            response = client.post(
                f"{server}/api/v1/auth/login",
                json={"username": username, "password": password},
            )
        _raise_for_status(response)
        return response.json()

    def verify_totp(
        self, server: str, auth_token: str, totp_code: str
    ) -> dict[str, Any]:
        """Verify a TOTP code to complete login or enrollment.

        During login: upgrades the intermediate auth_token to a full access token.
        During registration: confirms TOTP enrollment.

        Args:
            server: Base URL of the VPN server.
            auth_token: Intermediate JWT from login() or registration.
            totp_code: 6-digit TOTP code from the authenticator app.

        Returns:
            During login — dict with access_token, token_type, expires_in.
            During registration — dict with success, message.

        Raises:
            APIError: On 401 (invalid token), 400 (bad TOTP code).
        """
        with self._client() as client:
            response = client.post(
                f"{server}/api/v1/auth/totp/verify",
                json={"totp_code": totp_code},
                headers=self._auth_headers(auth_token),
            )
        _raise_for_status(response)
        return response.json()

    # ------------------------------------------------------------------
    # VPN session endpoints
    # ------------------------------------------------------------------

    def create_session(
        self,
        server: str,
        access_token: str,
        device_name: str,
        client_public_key: str,
    ) -> dict[str, Any]:
        """Create a new VPN session and register the client's public key.

        Args:
            server: Base URL of the VPN server.
            access_token: Full-access JWT (requires completed 2FA).
            device_name: Human-readable name for this device/session.
            client_public_key: WireGuard base64-encoded public key.

        Returns:
            Dict with session_id, server_public_key, server_endpoint,
            assigned_ip, dns_servers, allowed_ips, expires_at,
            keepalive_interval.

        Raises:
            APIError: On 401, 403, 409 (session limit / duplicate key), 503.
        """
        with self._client() as client:
            response = client.post(
                f"{server}/api/v1/vpn/sessions",
                json={
                    "device_name": device_name,
                    "client_public_key": client_public_key,
                },
                headers=self._auth_headers(access_token),
            )
        _raise_for_status(response)
        return response.json()

    def list_sessions(
        self, server: str, access_token: str
    ) -> dict[str, Any]:
        """List all VPN sessions for the current user.

        Args:
            server: Base URL of the VPN server.
            access_token: Full-access JWT.

        Returns:
            Dict with a 'sessions' list of session metadata dicts.

        Raises:
            APIError: On 401.
        """
        with self._client() as client:
            response = client.get(
                f"{server}/api/v1/vpn/sessions",
                headers=self._auth_headers(access_token),
            )
        _raise_for_status(response)
        return response.json()

    def revoke_session(
        self, server: str, access_token: str, session_id: str
    ) -> dict[str, Any]:
        """Revoke a VPN session, removing the WireGuard peer on the server.

        Args:
            server: Base URL of the VPN server.
            access_token: Full-access JWT.
            session_id: UUID of the session to revoke.

        Returns:
            Dict with session_id and status ('revoked').

        Raises:
            APIError: On 401, 404 (not found), 409 (already expired).
        """
        with self._client() as client:
            response = client.delete(
                f"{server}/api/v1/vpn/sessions/{session_id}",
                headers=self._auth_headers(access_token),
            )
        _raise_for_status(response)
        return response.json()

    # ------------------------------------------------------------------
    # Health endpoint
    # ------------------------------------------------------------------

    def health(self, server: str) -> dict[str, Any]:
        """Fetch the server health status (unauthenticated).

        Args:
            server: Base URL of the VPN server.

        Returns:
            Dict with status, wireguard ('up'|'down'), and version.

        Raises:
            httpx.ConnectError: If the server is unreachable.
        """
        with self._client() as client:
            response = client.get(f"{server}/api/v1/health")
        _raise_for_status(response)
        return response.json()
