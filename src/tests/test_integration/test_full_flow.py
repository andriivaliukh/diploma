"""
End-to-end integration tests.

These tests execute the full user journey through the API without mocking
any layers above the WireGuard boundary (which is still mocked since it
requires kernel-level access).

Flows tested:
1. Regular user: register → enroll TOTP → login → create VPN session → revoke session
2. Admin flow: admin login → list users → list sessions → force-revoke session → update settings
3. Security: unauthenticated requests, cross-user access, token scope enforcement
4. Health endpoint
"""
from __future__ import annotations

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import update

from vpnservice.models import TOTPSecret, User
from tests.conftest import (
    WG_PUBLIC_KEY_1,
    WG_PUBLIC_KEY_2,
    MockWireGuardManager,
    get_access_token,
)


# ── Health endpoint ───────────────────────────────────────────────────────────


class TestHealthEndpoint:
    async def test_health_returns_200(self, app_client: AsyncClient):
        resp = await app_client.get("/api/v1/health")
        assert resp.status_code == 200, (
            f"Health endpoint must return 200, got {resp.status_code}"
        )

    async def test_health_response_shape(self, app_client: AsyncClient):
        resp = await app_client.get("/api/v1/health")
        body = resp.json()
        assert "status" in body, "Health response must contain 'status'"

    async def test_health_status_is_healthy(self, app_client: AsyncClient):
        resp = await app_client.get("/api/v1/health")
        assert resp.json().get("status") == "healthy", (
            f"Health status must be 'healthy', got: {resp.json().get('status')}"
        )

    async def test_health_is_unauthenticated(self, app_client: AsyncClient):
        """Health endpoint must be publicly accessible without authentication."""
        resp = await app_client.get("/api/v1/health")
        assert resp.status_code == 200, "Health must not require authentication"


# ── Full user flow ────────────────────────────────────────────────────────────


class TestFullUserFlow:
    """
    E2E: register → complete TOTP enrollment → login → create session → revoke
    """

    async def test_complete_user_flow(
        self, app_client: AsyncClient, db_session, mock_wg_manager: MockWireGuardManager
    ):
        # 1. Register
        reg_resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "e2euser", "password": "password123"},
        )
        assert reg_resp.status_code == 201, f"Registration failed: {reg_resp.json()}"
        totp_secret = reg_resp.json()["totp_secret"]

        # 2. Mark TOTP enrolled (simulating enrollment confirmation)
        await db_session.execute(update(TOTPSecret).values(is_verified=True))
        await db_session.commit()

        # 3. Login with password → get intermediate token
        login_resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "e2euser", "password": "password123"},
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.json()}"
        assert login_resp.json().get("requires_totp") is True
        auth_token = login_resp.json()["auth_token"]

        # 4. Verify TOTP → get full access token
        code = pyotp.TOTP(totp_secret).now()
        verify_resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert verify_resp.status_code == 200, f"TOTP verify failed: {verify_resp.json()}"
        access_token = verify_resp.json().get("access_token")
        assert access_token is not None, "Must receive access_token after TOTP verify"
        headers = {"Authorization": f"Bearer {access_token}"}

        # 5. Create VPN session
        session_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "e2e-laptop", "client_public_key": WG_PUBLIC_KEY_1},
            headers=headers,
        )
        assert session_resp.status_code == 201, (
            f"Create session failed: {session_resp.json()}"
        )
        session_id = session_resp.json()["session_id"]
        assert session_resp.json()["assigned_ip"].startswith("10.10.")

        # WireGuard peer must have been added
        assert WG_PUBLIC_KEY_1 in mock_wg_manager.peers, (
            "Peer must be in WireGuard after session creation"
        )

        # 6. List sessions — must show the new session
        list_resp = await app_client.get("/api/v1/vpn/sessions", headers=headers)
        assert list_resp.status_code == 200
        session_ids = [s["session_id"] for s in list_resp.json()["sessions"]]
        assert session_id in session_ids, "Created session must appear in list"

        # 7. Get session details
        get_resp = await app_client.get(
            f"/api/v1/vpn/sessions/{session_id}", headers=headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] == "active"

        # 8. Revoke session
        revoke_resp = await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=headers
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["status"] == "revoked"

        # WireGuard peer must have been removed
        assert WG_PUBLIC_KEY_1 in mock_wg_manager.remove_peer_calls, (
            "Peer must be removed from WireGuard after revocation"
        )

        # 9. Session no longer active — can create a new one
        new_session_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "e2e-laptop2", "client_public_key": WG_PUBLIC_KEY_2},
            headers=headers,
        )
        assert new_session_resp.status_code == 201, (
            f"New session after revoke must succeed, got {new_session_resp.status_code}: {new_session_resp.json()}"
        )


# ── Admin flow ────────────────────────────────────────────────────────────────


class TestAdminFlow:
    async def test_admin_can_see_and_revoke_user_sessions(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
        mock_wg_manager: MockWireGuardManager,
    ):
        # Regular user creates a session
        session_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "user-laptop", "client_public_key": WG_PUBLIC_KEY_1},
            headers=auth_headers,
        )
        assert session_resp.status_code == 201
        session_id = session_resp.json()["session_id"]

        # Admin lists all sessions — must see user's session
        admin_sessions_resp = await app_client.get(
            "/api/v1/admin/sessions", headers=admin_auth_headers
        )
        assert admin_sessions_resp.status_code == 200
        all_sessions = admin_sessions_resp.json()["sessions"]
        all_ids = [s["session_id"] for s in all_sessions]
        assert session_id in all_ids, "Admin must see user's session"

        # Admin force-revokes the session
        revoke_resp = await app_client.delete(
            f"/api/v1/admin/sessions/{session_id}",
            headers=admin_auth_headers,
        )
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["status"] == "revoked"

        # WireGuard peer removed
        assert WG_PUBLIC_KEY_1 in mock_wg_manager.remove_peer_calls

        # User's session list now shows the session as revoked or absent
        user_sessions_resp = await app_client.get(
            "/api/v1/vpn/sessions", headers=auth_headers
        )
        assert user_sessions_resp.status_code == 200
        user_sessions = user_sessions_resp.json()["sessions"]
        session = next((s for s in user_sessions if s["session_id"] == session_id), None)
        if session:
            assert session["status"] in ("revoked", "expired"), (
                f"Session must be revoked/expired, got: {session['status']}"
            )

    async def test_admin_update_settings_affects_session_limit(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
    ):
        # Default limit is 1 — second session is rejected
        await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "d1", "client_public_key": WG_PUBLIC_KEY_1},
            headers=auth_headers,
        )
        second = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "d2", "client_public_key": WG_PUBLIC_KEY_2},
            headers=auth_headers,
        )
        assert second.status_code == 409, "Second session must fail with default limit=1"

        # Admin raises limit to 2
        await app_client.put(
            "/api/v1/admin/settings",
            json={"max_sessions_per_user": 2},
            headers=admin_auth_headers,
        )

        # Revoke first session so user can create a new one under new limit
        sessions_resp = await app_client.get("/api/v1/vpn/sessions", headers=auth_headers)
        first_id = sessions_resp.json()["sessions"][0]["session_id"]
        await app_client.delete(f"/api/v1/vpn/sessions/{first_id}", headers=auth_headers)

        # Now two sessions should succeed
        s1 = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "d3", "client_public_key": WG_PUBLIC_KEY_1},
            headers=auth_headers,
        )
        s2 = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "d4", "client_public_key": WG_PUBLIC_KEY_2},
            headers=auth_headers,
        )
        assert s1.status_code == 201
        assert s2.status_code == 201


# ── Security tests ────────────────────────────────────────────────────────────


class TestSecurityEnforcement:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/vpn/sessions"),
            ("POST", "/api/v1/vpn/sessions"),
            ("GET", "/api/v1/vpn/sessions/any-id"),
            ("DELETE", "/api/v1/vpn/sessions/any-id"),
            ("GET", "/api/v1/admin/users"),
            ("GET", "/api/v1/admin/sessions"),
            ("DELETE", "/api/v1/admin/sessions/any-id"),
            ("GET", "/api/v1/admin/settings"),
            ("PUT", "/api/v1/admin/settings"),
        ],
    )
    async def test_protected_endpoints_require_auth(
        self, app_client: AsyncClient, method: str, path: str
    ):
        """All protected endpoints must return 401 or 403 without a token."""
        if method == "GET":
            resp = await app_client.get(path)
        elif method == "POST":
            resp = await app_client.post(path, json={})
        elif method == "DELETE":
            resp = await app_client.delete(path)
        elif method == "PUT":
            resp = await app_client.put(path, json={})
        else:
            pytest.fail(f"Unknown method: {method}")

        assert resp.status_code in (401, 403), (
            f"{method} {path}: expected 401/403 without auth, got {resp.status_code}"
        )

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/admin/users"),
            ("GET", "/api/v1/admin/sessions"),
            ("DELETE", "/api/v1/admin/sessions/any-id"),
            ("GET", "/api/v1/admin/settings"),
            ("PUT", "/api/v1/admin/settings"),
        ],
    )
    async def test_admin_endpoints_block_regular_users(
        self, app_client: AsyncClient, auth_headers: dict, method: str, path: str
    ):
        """Admin endpoints must return 403 for authenticated non-admin users."""
        if method == "GET":
            resp = await app_client.get(path, headers=auth_headers)
        elif method == "DELETE":
            resp = await app_client.delete(path, headers=auth_headers)
        elif method == "PUT":
            resp = await app_client.put(path, json={}, headers=auth_headers)
        else:
            pytest.fail(f"Unknown method: {method}")

        assert resp.status_code == 403, (
            f"{method} {path}: non-admin must get 403, got {resp.status_code}"
        )

    async def test_intermediate_token_cannot_access_vpn(
        self, app_client: AsyncClient, registered_user
    ):
        """Intermediate token (scope=totp_verify) must not grant VPN access."""
        from tests.conftest import make_intermediate_token

        username, password, _ = registered_user
        # Get a real intermediate token
        login_resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        auth_token = login_resp.json()["auth_token"]

        resp = await app_client.get(
            "/api/v1/vpn/sessions",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 401, (
            f"Intermediate token must not access /vpn/sessions, got {resp.status_code}"
        )

    async def test_tampered_token_returns_401(self, app_client: AsyncClient, auth_headers: dict):
        """Modifying the JWT payload or signature must invalidate the token."""
        token = auth_headers["Authorization"].split(" ")[1]
        # Flip one char in the signature (last segment)
        parts = token.split(".")
        assert len(parts) == 3
        sig = parts[2]
        # Replace last char with a different one
        tampered_sig = sig[:-1] + ("A" if sig[-1] != "A" else "B")
        tampered = ".".join([parts[0], parts[1], tampered_sig])

        resp = await app_client.get(
            "/api/v1/vpn/sessions",
            headers={"Authorization": f"Bearer {tampered}"},
        )
        assert resp.status_code == 401, (
            f"Tampered token must return 401, got {resp.status_code}"
        )

    async def test_user_cannot_access_other_users_sessions(
        self,
        app_client: AsyncClient,
        auth_headers: dict,
        db_session,
    ):
        """User A's session must not be visible or deletable by user B."""
        # Register user B
        reg = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "userb", "password": "password456"},
        )
        assert reg.status_code == 201
        # Mark all TOTP secrets verified (registered_user's is already True;
        # this also covers the newly registered userb)
        await db_session.execute(update(TOTPSecret).values(is_verified=True))
        await db_session.commit()

        token_b = await get_access_token(
            app_client, "userb", "password456", reg.json()["totp_secret"]
        )
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A creates a session
        session_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "a-laptop", "client_public_key": WG_PUBLIC_KEY_1},
            headers=auth_headers,
        )
        assert session_resp.status_code == 201
        session_id = session_resp.json()["session_id"]

        # User B cannot see user A's session
        get_resp = await app_client.get(
            f"/api/v1/vpn/sessions/{session_id}", headers=headers_b
        )
        assert get_resp.status_code == 404, (
            f"User B must not see User A's session, got {get_resp.status_code}"
        )

        # User B cannot delete user A's session
        del_resp = await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=headers_b
        )
        assert del_resp.status_code in (403, 404), (
            f"User B must not delete User A's session, got {del_resp.status_code}"
        )
