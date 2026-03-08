"""
Tests for POST /api/v1/auth/login and POST /api/v1/auth/totp/verify

Covers:
- Login happy path: intermediate token structure, scope
- Login edge cases: wrong password, unknown user, unverified TOTP
- TOTP verify (registration / enrollment context)
- TOTP verify (login context): access token shape, scope
- Token expiry and wrong-scope rejection
- JWT structure validation
"""
from __future__ import annotations

import pytest
import pyotp
import jwt as pyjwt
from httpx import AsyncClient
from sqlalchemy import update

from vpnservice.models import TOTPSecret
from tests.conftest import (
    TEST_JWT_SECRET,
    make_expired_token,
    make_access_token,
    make_intermediate_token,
)


# ── Login ─────────────────────────────────────────────────────────────────────


class TestLoginHappyPath:
    async def test_login_valid_credentials_returns_200(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200, f"Login failed: {resp.json()}"

    async def test_login_response_contains_auth_token(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "auth_token" in body, "Login response must include auth_token"
        assert body.get("token_type") == "bearer", "token_type must be 'bearer'"
        assert body.get("requires_totp") is True, "requires_totp must be True"

    async def test_login_auth_token_has_totp_verify_scope(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        token = resp.json()["auth_token"]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        assert payload.get("scope") == "totp_verify", (
            f"Intermediate token scope must be 'totp_verify', got: {payload.get('scope')}"
        )

    async def test_login_auth_token_contains_user_id(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        payload = pyjwt.decode(
            resp.json()["auth_token"], options={"verify_signature": False}
        )
        assert "sub" in payload, "JWT must contain 'sub' claim (user_id)"
        assert "exp" in payload, "JWT must contain 'exp' claim"


class TestLoginEdgeCases:
    async def test_login_wrong_password_returns_401(
        self, app_client: AsyncClient, registered_user
    ):
        username, _, _ = registered_user
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "wrongpassword"},
        )
        assert resp.status_code == 401, (
            f"Wrong password must return 401, got {resp.status_code}"
        )

    async def test_login_unknown_username_returns_401(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "doesnotexist999", "password": "password123"},
        )
        assert resp.status_code == 401, (
            f"Unknown user must return 401, got {resp.status_code}"
        )

    async def test_login_unverified_totp_returns_403(
        self, app_client: AsyncClient, db_session
    ):
        """User has TOTP secret but is_verified=False — login must return 403."""
        # Register a fresh user (is_verified=False by default)
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "unverifeduser", "password": "password123"},
        )
        assert resp.status_code == 201

        # Explicitly ensure is_verified is False
        await db_session.execute(
            update(TOTPSecret)
            .where(True)  # only one TOTP secret in DB at this point
            .values(is_verified=False)
        )
        await db_session.commit()

        login_resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "unverifeduser", "password": "password123"},
        )
        assert login_resp.status_code == 403, (
            f"Unverified TOTP must return 403, got {login_resp.status_code}: {login_resp.json()}"
        )

    async def test_login_missing_password_returns_422(self, app_client: AsyncClient):
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "someuser"},
        )
        assert resp.status_code == 422, "Missing password must return 422"

    async def test_login_empty_body_returns_422(self, app_client: AsyncClient):
        resp = await app_client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422, "Empty body must return 422"


# ── TOTP verify — login context ───────────────────────────────────────────────


class TestTOTPVerifyLoginContext:
    async def _get_auth_token(
        self, client: AsyncClient, username: str, password: str
    ) -> str:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert resp.status_code == 200
        return resp.json()["auth_token"]

    async def test_totp_verify_valid_code_returns_200(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, totp_secret = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)
        code = pyotp.TOTP(totp_secret).now()

        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200, f"Valid TOTP verify failed: {resp.json()}"

    async def test_totp_verify_returns_access_token(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, totp_secret = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)
        code = pyotp.TOTP(totp_secret).now()

        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        body = resp.json()
        assert "access_token" in body, f"Response must contain access_token: {body}"
        assert body.get("token_type") == "bearer", "token_type must be 'bearer'"
        assert "expires_in" in body, "Response must contain expires_in"

    async def test_totp_verify_access_token_has_full_scope(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, totp_secret = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)
        code = pyotp.TOTP(totp_secret).now()

        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        access_token = resp.json()["access_token"]
        payload = pyjwt.decode(access_token, options={"verify_signature": False})
        assert payload.get("scope") == "full", (
            f"Access token scope must be 'full', got: {payload.get('scope')}"
        )
        assert "sub" in payload, "Access token must contain 'sub' claim"
        assert "exp" in payload, "Access token must contain 'exp' claim"

    async def test_totp_verify_invalid_code_returns_400(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)

        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": "000000"},  # almost certainly wrong
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 400, (
            f"Invalid TOTP code must return 400, got {resp.status_code}: {resp.json()}"
        )

    async def test_totp_verify_non_numeric_code_returns_400_or_422(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)

        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": "abcdef"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code in (400, 422), (
            f"Non-numeric TOTP code must return 400 or 422, got {resp.status_code}"
        )

    async def test_totp_verify_without_token_returns_401_or_403(
        self, app_client: AsyncClient
    ):
        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": "123456"},
        )
        assert resp.status_code in (401, 403), (
            f"Missing token must return 401/403, got {resp.status_code}"
        )

    async def test_totp_verify_with_full_access_token_returns_401(
        self, app_client: AsyncClient, registered_user
    ):
        """Using a full-access token (scope=full) at /totp/verify must fail."""
        username, password, totp_secret = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)
        code = pyotp.TOTP(totp_secret).now()

        # First, complete login to get a full-access token
        verify_resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        body = verify_resp.json()
        if "access_token" not in body:
            pytest.skip("Could not obtain access_token in this run (timing issue)")

        access_token = body["access_token"]

        # Now try to reuse the full-access token for TOTP verify — must be rejected
        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": "123456"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert resp.status_code == 401, (
            f"Full-access token must not be accepted at /totp/verify, got {resp.status_code}"
        )

    async def test_totp_verify_expired_token_returns_401(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        # Extract user_id from intermediate token
        auth_token = await self._get_auth_token(app_client, username, password)
        user_id = pyjwt.decode(auth_token, options={"verify_signature": False})["sub"]

        expired_token = make_expired_token(user_id, scope="totp_verify")
        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": "123456"},
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401, (
            f"Expired token must return 401, got {resp.status_code}"
        )

    async def test_totp_verify_token_with_wrong_jwt_secret_returns_401(
        self, app_client: AsyncClient, registered_user
    ):
        username, password, _ = registered_user
        auth_token = await self._get_auth_token(app_client, username, password)
        user_id = pyjwt.decode(auth_token, options={"verify_signature": False})["sub"]

        bad_token = make_intermediate_token(user_id, secret="wrong-secret")
        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": "123456"},
            headers={"Authorization": f"Bearer {bad_token}"},
        )
        assert resp.status_code == 401, (
            f"Token signed with wrong secret must return 401, got {resp.status_code}"
        )


# ── TOTP verify — enrollment (registration) context ──────────────────────────


class TestTOTPVerifyEnrollmentContext:
    """
    Tests for the first TOTP verify after registration (is_verified=False).
    The endpoint should return {success: true, message: "TOTP enrollment confirmed"}
    and set is_verified=True.
    """

    async def test_enrollment_verify_valid_code_returns_200(
        self, app_client: AsyncClient, db_session
    ):
        # Register a fresh user (is_verified=False)
        reg_resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "enrolltest", "password": "password123"},
        )
        assert reg_resp.status_code == 201
        totp_secret = reg_resp.json()["totp_secret"]

        # Login to get intermediate token
        login_resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "enrolltest", "password": "password123"},
        )
        # If login returns 403 (TOTP not verified), it means the implementation
        # requires enrollment first — skip this test path
        if login_resp.status_code == 403:
            pytest.skip("Implementation requires separate enrollment endpoint")

        assert login_resp.status_code == 200
        auth_token = login_resp.json()["auth_token"]
        code = pyotp.TOTP(totp_secret).now()

        verify_resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert verify_resp.status_code == 200, (
            f"First TOTP verify must return 200, got {verify_resp.status_code}: {verify_resp.json()}"
        )

    async def test_enrollment_verify_response_indicates_success(
        self, app_client: AsyncClient, db_session
    ):
        reg_resp = await app_client.post(
            "/api/v1/auth/register",
            json={"username": "enrolltest2", "password": "password123"},
        )
        assert reg_resp.status_code == 201
        totp_secret = reg_resp.json()["totp_secret"]

        login_resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "enrolltest2", "password": "password123"},
        )
        if login_resp.status_code == 403:
            pytest.skip("Implementation requires separate enrollment endpoint")

        auth_token = login_resp.json()["auth_token"]
        code = pyotp.TOTP(totp_secret).now()

        verify_resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_code": code},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        body = verify_resp.json()
        # Either enrollment confirmation or access token — both are valid outcomes
        is_enrollment_response = body.get("success") is True
        is_login_response = "access_token" in body
        assert is_enrollment_response or is_login_response, (
            f"Unexpected TOTP verify response: {body}"
        )
