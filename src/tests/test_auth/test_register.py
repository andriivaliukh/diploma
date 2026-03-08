"""
Tests for POST /api/v1/auth/register

Covers:
- Happy path: valid registration response shape
- Input validation: username length, charset, password strength
- Duplicate username conflict
"""
from __future__ import annotations

import base64

import pytest
from httpx import AsyncClient


class TestRegisterHappyPath:
    async def test_register_returns_201(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "newuser", "password": "password123"},
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.json()}"

    async def test_register_response_contains_required_fields(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "fielduser", "password": "password123"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "user_id" in body, "Response must include user_id"
        assert "username" in body, "Response must include username"
        assert "totp_secret" in body, "Response must include totp_secret"
        assert "totp_uri" in body, "Response must include totp_uri"
        assert "totp_qr_base64" in body, "Response must include totp_qr_base64"

    async def test_register_username_echoed_correctly(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "echouser", "password": "password123"},
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "echouser", "Returned username must match input"

    async def test_register_totp_uri_has_correct_scheme(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "uriuser", "password": "password123"},
        )
        assert resp.status_code == 201
        totp_uri = resp.json()["totp_uri"]
        assert totp_uri.startswith("otpauth://totp/"), (
            f"TOTP URI must start with 'otpauth://totp/', got: {totp_uri}"
        )
        assert "uriuser" in totp_uri, "TOTP URI must contain the username"

    async def test_register_totp_secret_is_valid_base32(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "b32user", "password": "password123"},
        )
        assert resp.status_code == 201
        secret = resp.json()["totp_secret"]
        try:
            base64.b32decode(secret, casefold=True)
        except Exception:
            pytest.fail(f"totp_secret is not valid base32: {secret!r}")

    async def test_register_qr_base64_is_decodable(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "qruser", "password": "password123"},
        )
        assert resp.status_code == 201
        qr_b64 = resp.json()["totp_qr_base64"]
        try:
            decoded = base64.b64decode(qr_b64)
            assert len(decoded) > 0, "QR code base64 must decode to non-empty bytes"
        except Exception:
            pytest.fail(f"totp_qr_base64 is not valid base64: {qr_b64[:40]}...")

    async def test_register_user_id_is_uuid_format(self, app_client: AsyncClient):
        import re

        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "uuiduser", "password": "password123"},
        )
        assert resp.status_code == 201
        user_id = resp.json()["user_id"]
        uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        assert re.match(uuid_pattern, user_id, re.IGNORECASE), (
            f"user_id must be a UUID, got: {user_id}"
        )


class TestRegisterInputValidation:
    @pytest.mark.parametrize(
        "username,password,description",
        [
            ("ab", "password123", "username too short (< 3 chars)"),
            ("a" * 51, "password123", "username too long (> 50 chars)"),
            ("user name", "password123", "username contains space"),
            ("user!", "password123", "username contains special char '!'"),
            ("user@name", "password123", "username contains '@'"),
            ("user-name", "password123", "username contains hyphen"),
            ("validuser", "short", "password too short (< 8 chars)"),
            ("validuser", "1234567", "password exactly 7 chars (too short)"),
            ("validuser", "", "empty password"),
        ],
    )
    async def test_register_invalid_input_returns_422(
        self, app_client: AsyncClient, username: str, password: str, description: str
    ):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 422, (
            f"[{description}] Expected 422, got {resp.status_code}: {resp.json()}"
        )

    @pytest.mark.parametrize(
        "username,description",
        [
            ("abc", "minimum valid length (3 chars)"),
            ("a" * 50, "maximum valid length (50 chars)"),
            ("user_name", "underscore allowed"),
            ("User123", "mixed case and digits allowed"),
            ("abc123", "alphanumeric"),
        ],
    )
    async def test_register_valid_usernames_accepted(
        self, app_client: AsyncClient, username: str, description: str
    ):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "password123"},
        )
        assert resp.status_code == 201, (
            f"[{description}] Expected 201, got {resp.status_code}: {resp.json()}"
        )

    async def test_register_minimum_password_length_accepted(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "passuser", "password": "12345678"},  # exactly 8 chars
        )
        assert resp.status_code == 201, (
            f"Password of exactly 8 chars must be accepted, got {resp.status_code}"
        )

    async def test_register_missing_password_returns_422(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "missingpw"},
        )
        assert resp.status_code == 422, "Missing password field must return 422"

    async def test_register_missing_username_returns_422(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"password": "password123"},
        )
        assert resp.status_code == 422, "Missing username field must return 422"

    async def test_register_empty_body_returns_422(self, app_client: AsyncClient):
        resp = await app_client.post("/api/v1/auth/register", json={})
        assert resp.status_code == 422, "Empty body must return 422"


class TestRegisterConflicts:
    async def test_register_duplicate_username_returns_409(self, app_client: AsyncClient):
        payload = {"username": "dupuser", "password": "password123"}

        first = await app_client.post("/api/v1/auth/register", json=payload)
        assert first.status_code == 201, f"First registration failed: {first.json()}"

        second = await app_client.post("/api/v1/auth/register", json=payload)
        assert second.status_code == 409, (
            f"Duplicate username must return 409, got {second.status_code}: {second.json()}"
        )

    async def test_register_duplicate_username_case_sensitive(self, app_client: AsyncClient):
        """Two registrations with same letters but different case — behaviour is
        implementation-defined; at minimum both must not cause a 5xx error."""
        await app_client.post(
            "/api/v1/auth/register",
            json={"username": "CaseUser", "password": "password123"},
        )
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "caseuser", "password": "password123"},
        )
        assert resp.status_code in (201, 409), (
            f"Case-variant registration must return 201 or 409, got {resp.status_code}"
        )
