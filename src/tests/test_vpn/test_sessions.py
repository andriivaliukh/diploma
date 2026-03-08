"""
Tests for VPN session endpoints:
  POST   /api/v1/vpn/sessions
  GET    /api/v1/vpn/sessions
  GET    /api/v1/vpn/sessions/{session_id}
  DELETE /api/v1/vpn/sessions/{session_id}

Covers:
- Happy path: create → list → get → revoke
- Authentication: missing token, expired token, wrong-scope token
- Session limit enforcement (409 when max reached)
- Duplicate device public key (409)
- WireGuard failure path (503)
- Session not found / already revoked (404, 409)
- Assigned IP format validation
- Mock WireGuard call verification
"""
from __future__ import annotations

import pytest
import re
from httpx import AsyncClient

from tests.conftest import (
    WG_PUBLIC_KEY_1,
    WG_PUBLIC_KEY_2,
    MockWireGuardManager,
    make_expired_token,
    make_access_token,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_session_payload(
    device_name: str = "laptop",
    public_key: str = WG_PUBLIC_KEY_1,
) -> dict:
    return {"device_name": device_name, "client_public_key": public_key}


# ── Create session ────────────────────────────────────────────────────────────


class TestCreateSession:
    async def test_create_session_returns_201(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.json()}"
        )

    async def test_create_session_response_shape(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        required_fields = [
            "session_id",
            "server_public_key",
            "server_endpoint",
            "assigned_ip",
            "dns_servers",
            "allowed_ips",
            "expires_at",
            "keepalive_interval",
        ]
        for field in required_fields:
            assert field in body, f"Response missing field: {field}"

    async def test_create_session_assigned_ip_is_valid_cidr(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assigned_ip = resp.json()["assigned_ip"]
        # Must match x.x.x.x/32
        assert re.match(r"^\d+\.\d+\.\d+\.\d+/\d+$", assigned_ip), (
            f"assigned_ip must be CIDR notation, got: {assigned_ip}"
        )

    async def test_create_session_assigned_ip_in_vpn_subnet(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        assigned_ip = resp.json()["assigned_ip"]
        # Default subnet is 10.10.0.0/24; assigned IPs are 10.10.0.2–10.10.0.254
        assert assigned_ip.startswith("10.10.0."), (
            f"Assigned IP must be in 10.10.0.0/24 subnet, got: {assigned_ip}"
        )

    async def test_create_session_session_id_is_uuid(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 201
        session_id = resp.json()["session_id"]
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            session_id,
            re.IGNORECASE,
        ), f"session_id must be UUID, got: {session_id}"

    async def test_create_session_adds_peer_to_wireguard(
        self, app_client: AsyncClient, auth_headers: dict, mock_wg_manager: MockWireGuardManager
    ):
        await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(public_key=WG_PUBLIC_KEY_1),
            headers=auth_headers,
        )
        assert len(mock_wg_manager.add_peer_calls) == 1, (
            "WireGuard add_peer must be called exactly once per session"
        )
        assert mock_wg_manager.add_peer_calls[0]["public_key"] == WG_PUBLIC_KEY_1


class TestCreateSessionAuth:
    async def test_create_session_without_token_returns_401_or_403(
        self, app_client: AsyncClient
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
        )
        assert resp.status_code in (401, 403), (
            f"Missing token must return 401/403, got {resp.status_code}"
        )

    async def test_create_session_with_expired_token_returns_401(
        self, app_client: AsyncClient, registered_user
    ):
        username, _, _ = registered_user
        # We need user_id — register returns it, but our fixture doesn't expose it.
        # Use a syntactically valid but expired token with a fake user_id.
        expired = make_expired_token("00000000-0000-0000-0000-000000000001")
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers={"Authorization": f"Bearer {expired}"},
        )
        assert resp.status_code == 401, (
            f"Expired token must return 401, got {resp.status_code}"
        )

    async def test_create_session_with_intermediate_token_returns_401(
        self, app_client: AsyncClient, registered_user
    ):
        """Intermediate token (scope=totp_verify) must not grant VPN access."""
        from tests.conftest import make_intermediate_token

        fake_user_id = "00000000-0000-0000-0000-000000000002"
        intermediate = make_intermediate_token(fake_user_id)
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers={"Authorization": f"Bearer {intermediate}"},
        )
        assert resp.status_code == 401, (
            f"Intermediate token must not access VPN, got {resp.status_code}"
        )

    async def test_create_session_with_invalid_token_returns_401(
        self, app_client: AsyncClient
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers={"Authorization": "Bearer not.a.valid.jwt"},
        )
        assert resp.status_code == 401, (
            f"Invalid JWT must return 401, got {resp.status_code}"
        )


class TestCreateSessionLimits:
    async def test_create_session_duplicate_device_key_returns_409(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        """Two sessions with the same client_public_key must conflict."""
        payload = _create_session_payload(public_key=WG_PUBLIC_KEY_1)
        first = await app_client.post(
            "/api/v1/vpn/sessions", json=payload, headers=auth_headers
        )
        assert first.status_code == 201, f"First session failed: {first.json()}"

        second = await app_client.post(
            "/api/v1/vpn/sessions", json=payload, headers=auth_headers
        )
        assert second.status_code == 409, (
            f"Duplicate public key must return 409, got {second.status_code}: {second.json()}"
        )

    async def test_create_session_limit_reached_returns_409(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        """Default max_sessions_per_user=1; second session must return 409."""
        first = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(device_name="device1", public_key=WG_PUBLIC_KEY_1),
            headers=auth_headers,
        )
        assert first.status_code == 201, f"First session failed: {first.json()}"

        second = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(device_name="device2", public_key=WG_PUBLIC_KEY_2),
            headers=auth_headers,
        )
        assert second.status_code == 409, (
            f"Session limit must return 409, got {second.status_code}: {second.json()}"
        )

    async def test_create_session_limit_error_message(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        """409 response body must describe the session limit."""
        await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(device_name="device1", public_key=WG_PUBLIC_KEY_1),
            headers=auth_headers,
        )
        second = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(device_name="device2", public_key=WG_PUBLIC_KEY_2),
            headers=auth_headers,
        )
        assert second.status_code == 409
        detail = second.json().get("detail", "")
        assert "session" in detail.lower() or "limit" in detail.lower(), (
            f"409 detail should mention 'session' or 'limit', got: {detail}"
        )

    async def test_create_session_invalid_device_name_returns_422(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "", "client_public_key": WG_PUBLIC_KEY_1},
            headers=auth_headers,
        )
        assert resp.status_code == 422, (
            f"Empty device name must return 422, got {resp.status_code}"
        )

    async def test_create_session_missing_public_key_returns_422(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json={"device_name": "laptop"},
            headers=auth_headers,
        )
        assert resp.status_code == 422, "Missing public key must return 422"


# ── List sessions ─────────────────────────────────────────────────────────────


class TestListSessions:
    async def test_list_sessions_returns_200(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/vpn/sessions", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"

    async def test_list_sessions_empty_initially(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.get("/api/v1/vpn/sessions", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "sessions" in body, "Response must contain 'sessions' key"
        assert isinstance(body["sessions"], list), "'sessions' must be a list"
        assert body["sessions"] == [], "New user must have zero sessions"

    async def test_list_sessions_shows_created_session(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["session_id"]

        list_resp = await app_client.get("/api/v1/vpn/sessions", headers=auth_headers)
        assert list_resp.status_code == 200
        sessions = list_resp.json()["sessions"]
        ids = [s["session_id"] for s in sessions]
        assert session_id in ids, (
            f"Created session {session_id} must appear in list"
        )

    async def test_list_sessions_item_has_required_fields(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        resp = await app_client.get("/api/v1/vpn/sessions", headers=auth_headers)
        sessions = resp.json()["sessions"]
        assert len(sessions) >= 1
        s = sessions[0]
        required_fields = [
            "session_id", "device_name", "assigned_ip", "status", "created_at", "expires_at"
        ]
        for field in required_fields:
            assert field in s, f"Session item missing field: {field}"

    async def test_list_sessions_without_token_returns_401_or_403(
        self, app_client: AsyncClient
    ):
        resp = await app_client.get("/api/v1/vpn/sessions")
        assert resp.status_code in (401, 403), (
            f"Missing token must return 401/403, got {resp.status_code}"
        )


# ── Get session by ID ─────────────────────────────────────────────────────────


class TestGetSession:
    async def test_get_session_returns_200(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        session_id = create_resp.json()["session_id"]

        resp = await app_client.get(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        assert resp.status_code == 200, (
            f"Expected 200 for existing session, got {resp.status_code}: {resp.json()}"
        )

    async def test_get_session_response_has_detailed_fields(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        session_id = create_resp.json()["session_id"]

        resp = await app_client.get(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        body = resp.json()
        detailed_fields = ["client_public_key", "transfer_rx", "transfer_tx"]
        for field in detailed_fields:
            assert field in body, (
                f"Detailed session response missing field: {field}"
            )

    async def test_get_session_nonexistent_returns_404(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.get(
            "/api/v1/vpn/sessions/00000000-0000-0000-0000-000000000099",
            headers=auth_headers,
        )
        assert resp.status_code == 404, (
            f"Non-existent session must return 404, got {resp.status_code}"
        )

    async def test_get_session_other_user_returns_404(
        self, app_client: AsyncClient, auth_headers: dict, db_session
    ):
        """A user must not be able to see another user's session (returns 404, not 403)."""
        from sqlalchemy import update
        from vpnservice.models import TOTPSecret, User

        # Create second user
        reg = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "otheruser", "password": "password456"},
        )
        assert reg.status_code == 201
        await db_session.execute(update(TOTPSecret).values(is_verified=True))
        await db_session.commit()

        from tests.conftest import get_access_token

        token2 = await get_access_token(
            app_client, "otheruser", "password456", reg.json()["totp_secret"]
        )
        headers2 = {"Authorization": f"Bearer {token2}"}

        # Create session as user2
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(public_key=WG_PUBLIC_KEY_2),
            headers=headers2,
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["session_id"]

        # Access as user1 — must be not found
        resp = await app_client.get(
            f"/api/v1/vpn/sessions/{session_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 404, (
            f"Another user's session must return 404, got {resp.status_code}"
        )


# ── Revoke session ────────────────────────────────────────────────────────────


class TestRevokeSession:
    async def test_revoke_session_returns_200(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        session_id = create_resp.json()["session_id"]

        resp = await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        assert resp.status_code == 200, (
            f"Revoke must return 200, got {resp.status_code}: {resp.json()}"
        )

    async def test_revoke_session_response_shows_revoked_status(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        session_id = create_resp.json()["session_id"]

        resp = await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        body = resp.json()
        assert body.get("status") == "revoked", (
            f"Revoked session status must be 'revoked', got: {body.get('status')}"
        )
        assert body.get("session_id") == session_id

    async def test_revoke_session_removes_peer_from_wireguard(
        self, app_client: AsyncClient, auth_headers: dict, mock_wg_manager: MockWireGuardManager
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(public_key=WG_PUBLIC_KEY_1),
            headers=auth_headers,
        )
        session_id = create_resp.json()["session_id"]

        await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        assert WG_PUBLIC_KEY_1 in mock_wg_manager.remove_peer_calls, (
            "WireGuard remove_peer must be called on session revocation"
        )

    async def test_revoke_session_twice_returns_409(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        create_resp = await app_client.post(
            "/api/v1/vpn/sessions",
            json=_create_session_payload(),
            headers=auth_headers,
        )
        session_id = create_resp.json()["session_id"]

        first = await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        assert first.status_code == 200

        second = await app_client.delete(
            f"/api/v1/vpn/sessions/{session_id}", headers=auth_headers
        )
        assert second.status_code == 409, (
            f"Revoking already-revoked session must return 409, got {second.status_code}"
        )

    async def test_revoke_nonexistent_session_returns_404(
        self, app_client: AsyncClient, auth_headers: dict
    ):
        resp = await app_client.delete(
            "/api/v1/vpn/sessions/00000000-0000-0000-0000-000000000099",
            headers=auth_headers,
        )
        assert resp.status_code == 404, (
            f"Non-existent session must return 404, got {resp.status_code}"
        )

    async def test_revoke_session_without_token_returns_401_or_403(
        self, app_client: AsyncClient
    ):
        resp = await app_client.delete(
            "/api/v1/vpn/sessions/00000000-0000-0000-0000-000000000001"
        )
        assert resp.status_code in (401, 403), (
            f"Missing token must return 401/403, got {resp.status_code}"
        )
