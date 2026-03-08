"""
Tests for admin endpoints:
  GET    /api/v1/admin/users
  GET    /api/v1/admin/sessions
  DELETE /api/v1/admin/sessions/{session_id}
  GET    /api/v1/admin/settings
  PUT    /api/v1/admin/settings

Covers:
- Happy path for all admin endpoints
- Authorization: non-admin user gets 403, unauthenticated gets 401
- Settings validation (422 for invalid values)
- Force-revoke removes WireGuard peer
- Edge cases: revoke already-revoked session, revoke non-existent session
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from vpnservice.models import TOTPSecret
from tests.conftest import (
    WG_PUBLIC_KEY_1,
    WG_PUBLIC_KEY_2,
    MockWireGuardManager,
    get_access_token,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _create_vpn_session(
    client: AsyncClient, headers: dict, device_name: str = "laptop", public_key: str = WG_PUBLIC_KEY_1
) -> dict:
    resp = await client.post(
        "/api/v1/vpn/sessions",
        json={"device_name": device_name, "client_public_key": public_key},
        headers=headers,
    )
    assert resp.status_code == 201, f"Session creation failed: {resp.json()}"
    return resp.json()


# ── List users ────────────────────────────────────────────────────────────────


class TestAdminListUsers:
    async def test_admin_list_users_returns_200(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/users", headers=admin_auth_headers)
        assert resp.status_code == 200, (
            f"Admin list users must return 200, got {resp.status_code}: {resp.json()}"
        )

    async def test_admin_list_users_response_shape(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/users", headers=admin_auth_headers)
        body = resp.json()
        assert "users" in body, "Response must contain 'users' list"
        assert isinstance(body["users"], list)

    async def test_admin_list_users_item_fields(
        self, app_client: AsyncClient, admin_auth_headers: dict, registered_user
    ):
        """After registering a second user, admin list must include them with required fields."""
        resp = await app_client.get("/api/v1/admin/users", headers=admin_auth_headers)
        users = resp.json()["users"]
        assert len(users) >= 1, "Must have at least one user (the admin)"
        user = users[0]
        required_fields = [
            "user_id", "username", "is_admin", "is_active",
            "totp_enrolled", "created_at", "active_sessions_count"
        ]
        for field in required_fields:
            assert field in user, f"User item missing field: {field}"

    async def test_non_admin_list_users_returns_403(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/users", headers=auth_headers)
        assert resp.status_code == 403, (
            f"Non-admin must get 403 on admin endpoint, got {resp.status_code}"
        )

    async def test_unauthenticated_list_users_returns_401_or_403(
        self, app_client: AsyncClient
    ):
        resp = await app_client.get("/api/v1/admin/users")
        assert resp.status_code in (401, 403), (
            f"Unauthenticated request must return 401/403, got {resp.status_code}"
        )


# ── List sessions (admin) ─────────────────────────────────────────────────────


class TestAdminListSessions:
    async def test_admin_list_sessions_returns_200(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/sessions", headers=admin_auth_headers)
        assert resp.status_code == 200, (
            f"Admin list sessions must return 200, got {resp.status_code}"
        )

    async def test_admin_list_sessions_shows_all_users_sessions(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
    ):
        """Admin can see sessions from non-admin users."""
        await _create_vpn_session(app_client, auth_headers, public_key=WG_PUBLIC_KEY_1)

        resp = await app_client.get("/api/v1/admin/sessions", headers=admin_auth_headers)
        assert resp.status_code == 200
        sessions = resp.json().get("sessions", [])
        assert len(sessions) >= 1, "Admin must see the user's session"

    async def test_admin_list_sessions_item_has_username(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
    ):
        await _create_vpn_session(app_client, auth_headers, public_key=WG_PUBLIC_KEY_1)

        resp = await app_client.get("/api/v1/admin/sessions", headers=admin_auth_headers)
        sessions = resp.json().get("sessions", [])
        if sessions:
            s = sessions[0]
            assert "username" in s or "user_id" in s, (
                "Admin session item must include user identity"
            )

    async def test_non_admin_list_sessions_returns_403(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/sessions", headers=auth_headers)
        assert resp.status_code == 403, (
            f"Non-admin must get 403, got {resp.status_code}"
        )


# ── Force-revoke session (admin) ──────────────────────────────────────────────


class TestAdminRevokeSession:
    async def test_admin_revoke_session_returns_200(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
        mock_wg_manager: MockWireGuardManager,
    ):
        session = await _create_vpn_session(app_client, auth_headers, public_key=WG_PUBLIC_KEY_1)
        session_id = session["session_id"]

        resp = await app_client.delete(
            f"/api/v1/admin/sessions/{session_id}",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, (
            f"Admin revoke must return 200, got {resp.status_code}: {resp.json()}"
        )

    async def test_admin_revoke_session_status_is_revoked(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
    ):
        session = await _create_vpn_session(app_client, auth_headers, public_key=WG_PUBLIC_KEY_1)
        session_id = session["session_id"]

        resp = await app_client.delete(
            f"/api/v1/admin/sessions/{session_id}",
            headers=admin_auth_headers,
        )
        body = resp.json()
        assert body.get("status") == "revoked", (
            f"Admin-revoked session status must be 'revoked', got: {body}"
        )

    async def test_admin_revoke_calls_wireguard_remove_peer(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
        mock_wg_manager: MockWireGuardManager,
    ):
        await _create_vpn_session(app_client, auth_headers, public_key=WG_PUBLIC_KEY_1)
        sessions_resp = await app_client.get(
            "/api/v1/admin/sessions", headers=admin_auth_headers
        )
        session_id = sessions_resp.json()["sessions"][0]["session_id"]

        await app_client.delete(
            f"/api/v1/admin/sessions/{session_id}",
            headers=admin_auth_headers,
        )
        assert WG_PUBLIC_KEY_1 in mock_wg_manager.remove_peer_calls, (
            "WireGuard remove_peer must be called when admin revokes a session"
        )

    async def test_admin_revoke_nonexistent_session_returns_404(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.delete(
            "/api/v1/admin/sessions/00000000-0000-0000-0000-000000000099",
            headers=admin_auth_headers,
        )
        assert resp.status_code == 404, (
            f"Non-existent session must return 404, got {resp.status_code}"
        )

    async def test_admin_revoke_already_revoked_returns_409(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
    ):
        session = await _create_vpn_session(app_client, auth_headers, public_key=WG_PUBLIC_KEY_1)
        session_id = session["session_id"]

        # First revoke
        first = await app_client.delete(
            f"/api/v1/admin/sessions/{session_id}", headers=admin_auth_headers
        )
        assert first.status_code == 200

        # Second revoke
        second = await app_client.delete(
            f"/api/v1/admin/sessions/{session_id}", headers=admin_auth_headers
        )
        assert second.status_code == 409, (
            f"Re-revoking already-revoked session must return 409, got {second.status_code}"
        )

    async def test_non_admin_revoke_session_returns_403(
        self,
        app_client: AsyncClient,
        auth_headers: dict,
    ):
        resp = await app_client.delete(
            "/api/v1/admin/sessions/00000000-0000-0000-0000-000000000001",
            headers=auth_headers,
        )
        assert resp.status_code == 403, (
            f"Non-admin revoke must return 403, got {resp.status_code}"
        )


# ── Settings ──────────────────────────────────────────────────────────────────


class TestAdminSettings:
    async def test_get_settings_returns_200(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/settings", headers=admin_auth_headers)
        assert resp.status_code == 200, (
            f"Get settings must return 200, got {resp.status_code}: {resp.json()}"
        )

    async def test_get_settings_response_shape(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/settings", headers=admin_auth_headers)
        body = resp.json()
        assert "max_sessions_per_user" in body, "Settings must include max_sessions_per_user"
        assert "session_ttl_hours" in body, "Settings must include session_ttl_hours"

    async def test_get_settings_default_values(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/settings", headers=admin_auth_headers)
        body = resp.json()
        assert body["max_sessions_per_user"] == 1, (
            f"Default max_sessions_per_user must be 1, got {body['max_sessions_per_user']}"
        )
        assert body["session_ttl_hours"] == 8, (
            f"Default session_ttl_hours must be 8, got {body['session_ttl_hours']}"
        )

    async def test_update_settings_returns_200(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        resp = await app_client.put(
            "/api/v1/admin/settings",
            json={"max_sessions_per_user": 3, "session_ttl_hours": 12},
            headers=admin_auth_headers,
        )
        assert resp.status_code == 200, (
            f"Update settings must return 200, got {resp.status_code}: {resp.json()}"
        )

    async def test_update_settings_persists(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        await app_client.put(
            "/api/v1/admin/settings",
            json={"max_sessions_per_user": 5, "session_ttl_hours": 24},
            headers=admin_auth_headers,
        )
        get_resp = await app_client.get(
            "/api/v1/admin/settings", headers=admin_auth_headers
        )
        body = get_resp.json()
        assert body["max_sessions_per_user"] == 5
        assert body["session_ttl_hours"] == 24

    async def test_update_settings_partial_update(
        self, app_client: AsyncClient, admin_auth_headers: dict
    ):
        """PUT with only one field should update only that field."""
        await app_client.put(
            "/api/v1/admin/settings",
            json={"max_sessions_per_user": 2},
            headers=admin_auth_headers,
        )
        get_resp = await app_client.get(
            "/api/v1/admin/settings", headers=admin_auth_headers
        )
        body = get_resp.json()
        assert body["max_sessions_per_user"] == 2
        # session_ttl_hours should remain default (8)
        assert body["session_ttl_hours"] == 8

    @pytest.mark.parametrize(
        "payload,description",
        [
            ({"max_sessions_per_user": 0}, "max_sessions_per_user=0 (< 1)"),
            ({"max_sessions_per_user": -1}, "max_sessions_per_user=-1"),
            ({"session_ttl_hours": 0}, "session_ttl_hours=0"),
            ({"session_ttl_hours": -5}, "session_ttl_hours negative"),
        ],
    )
    async def test_update_settings_invalid_values_returns_422(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        payload: dict,
        description: str,
    ):
        resp = await app_client.put(
            "/api/v1/admin/settings",
            json=payload,
            headers=admin_auth_headers,
        )
        assert resp.status_code == 422, (
            f"[{description}] Invalid settings must return 422, got {resp.status_code}: {resp.json()}"
        )

    async def test_non_admin_get_settings_returns_403(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/admin/settings", headers=auth_headers)
        assert resp.status_code == 403, (
            f"Non-admin get settings must return 403, got {resp.status_code}"
        )

    async def test_non_admin_update_settings_returns_403(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.put(
            "/api/v1/admin/settings",
            json={"max_sessions_per_user": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 403, (
            f"Non-admin update settings must return 403, got {resp.status_code}"
        )

    async def test_update_settings_session_limit_enforced_after_change(
        self,
        app_client: AsyncClient,
        admin_auth_headers: dict,
        auth_headers: dict,
    ):
        """After raising max_sessions_per_user to 2, two sessions should succeed."""
        # Raise limit
        await app_client.put(
            "/api/v1/admin/settings",
            json={"max_sessions_per_user": 2},
            headers=admin_auth_headers,
        )

        # First session
        s1 = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "device1", "client_public_key": WG_PUBLIC_KEY_1},
            headers=auth_headers,
        )
        assert s1.status_code == 201, f"First session failed: {s1.json()}"

        # Second session (should now succeed)
        s2 = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "device2", "client_public_key": WG_PUBLIC_KEY_2},
            headers=auth_headers,
        )
        assert s2.status_code == 201, (
            f"Second session must succeed after limit raised to 2, got {s2.status_code}: {s2.json()}"
        )
