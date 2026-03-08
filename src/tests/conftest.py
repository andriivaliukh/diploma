"""
Pytest configuration and shared fixtures for VPN Service tests.

Provides:
- In-memory SQLite database (isolated per test)
- FastAPI AsyncClient with dependency overrides
- MockWireGuardManager that records calls
- Helper factories for test users, tokens, WireGuard keys
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import jwt as pyjwt
import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import vpnservice.database as _db_module
from vpnservice.config import Settings, get_settings
from vpnservice.database import get_db
from vpnservice.models import Base, SystemSettings, TOTPSecret, User
from vpnservice.wireguard.manager import WireGuardError
from vpnservice.wireguard.schemas import PeerStats

# ── Constants ─────────────────────────────────────────────────────────────────

# Valid Fernet key (32 bytes URL-safe base64) — used for TOTP secret encryption in tests
# Decodes to b"test_fernet_key_for_testing_only" (exactly 32 bytes)
TEST_FERNET_KEY = "dGVzdF9mZXJuZXRfa2V5X2Zvcl90ZXN0aW5nX29ubHk="

# JWT secret for test token generation
TEST_JWT_SECRET = "test-jwt-secret-for-tests-only-not-production"

# Fake WireGuard public keys (32 null bytes, valid base64 = 44 chars each)
# base64.b64encode(bytes([i] * 32)).decode() for i in 0..9
WG_PUBLIC_KEYS = [base64.b64encode(bytes([i + 1] * 32)).decode() for i in range(10)]
WG_PUBLIC_KEY_1 = WG_PUBLIC_KEYS[0]
WG_PUBLIC_KEY_2 = WG_PUBLIC_KEYS[1]


# ── Mock WireGuardManager ─────────────────────────────────────────────────────


class MockWireGuardManager:
    """
    Mock WireGuardManager for testing.

    Records all add_peer / remove_peer calls, returns predictable PeerStats,
    and can be configured to simulate WireGuard failures.
    """

    SERVER_PUBLIC_KEY = base64.b64encode(b"server-public-key-test-000000000").decode()
    SERVER_ENDPOINT = "vpn.test.example.com:51820"

    def __init__(self) -> None:
        self.peers: dict[str, str] = {}  # public_key → allowed_ips
        self.add_peer_calls: list[dict] = []
        self.remove_peer_calls: list[str] = []
        self._fail_mode = False

    def set_fail_mode(self, fail: bool = True) -> None:
        """Make the next WireGuard operation raise RuntimeError."""
        self._fail_mode = fail

    def reset(self) -> None:
        """Clear all recorded calls and peer state."""
        self.peers.clear()
        self.add_peer_calls.clear()
        self.remove_peer_calls.clear()
        self._fail_mode = False

    async def initialize(self) -> None:
        pass

    async def add_peer(
        self,
        public_key: str,
        allowed_ips: str,
        preshared_key: str | None = None,
    ) -> None:
        if self._fail_mode:
            raise WireGuardError("WireGuard interface not available")
        self.peers[public_key] = allowed_ips
        self.add_peer_calls.append(
            {"public_key": public_key, "allowed_ips": allowed_ips, "preshared_key": preshared_key}
        )

    async def remove_peer(self, public_key: str) -> None:
        if self._fail_mode:
            raise WireGuardError("WireGuard interface not available")
        self.peers.pop(public_key, None)
        self.remove_peer_calls.append(public_key)

    async def get_peer_stats(self, public_key: str) -> PeerStats | None:
        if public_key not in self.peers:
            return None
        return PeerStats(
            public_key=public_key,
            allowed_ips=self.peers[public_key],
            last_handshake=datetime(2026, 3, 9, 12, 0, 0, tzinfo=timezone.utc),
            transfer_rx=1024,
            transfer_tx=2048,
        )

    async def list_peers(self) -> list[PeerStats]:
        return [
            PeerStats(
                public_key=pk,
                allowed_ips=ips,
                last_handshake=None,
                transfer_rx=0,
                transfer_tx=0,
            )
            for pk, ips in self.peers.items()
        ]

    def get_server_public_key(self) -> str:
        return self.SERVER_PUBLIC_KEY

    def get_endpoint(self) -> str:
        return self.SERVER_ENDPOINT


# ── Settings fixture ──────────────────────────────────────────────────────────


@pytest.fixture
def test_settings() -> Settings:
    """Test Settings with known secrets and in-memory database."""
    return Settings(
        secret_key=TEST_FERNET_KEY,
        jwt_secret=TEST_JWT_SECRET,
        jwt_access_ttl=86400,
        jwt_intermediate_ttl=300,
        wg_endpoint="vpn.test.example.com:51820",
        wg_subnet="10.10.0.0/24",
        wg_interface="wg0",
        db_path=":memory:",
    )


# ── Database fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
async def db_engine():
    """In-memory SQLite engine with all ORM tables created."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Database session for direct DB manipulation in tests."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


# ── Mock WireGuard fixture ────────────────────────────────────────────────────


@pytest.fixture
def mock_wg_manager() -> MockWireGuardManager:
    """Fresh MockWireGuardManager for each test."""
    return MockWireGuardManager()


# ── Application client fixture ────────────────────────────────────────────────


@pytest.fixture
async def app_client(
    db_engine, mock_wg_manager, test_settings
) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.AsyncClient backed by the FastAPI app.

    Overrides:
    - get_db  →  in-memory SQLite session
    - get_settings  →  test Settings
    - get_wireguard_manager  →  MockWireGuardManager (if dependency exists)
    """
    from vpnservice.main import app

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    def _override_get_settings() -> Settings:
        return test_settings

    # Seed singleton system settings row
    async with factory() as session:
        session.add(
            SystemSettings(
                id=1,
                max_sessions_per_user=1,
                session_ttl_hours=8,
                updated_at=datetime.now(tz=timezone.utc),
            )
        )
        await session.commit()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = _override_get_settings

    from vpnservice.vpn.router import get_wg_manager
    app.dependency_overrides[get_wg_manager] = lambda: mock_wg_manager

    _orig_engine = _db_module._engine
    _orig_session_factory = _db_module._session_factory
    _db_module._engine = db_engine
    _db_module._session_factory = factory

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()
    _db_module._engine = _orig_engine
    _db_module._session_factory = _orig_session_factory


# ── User fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
async def registered_user(app_client, db_session) -> tuple[str, str, str]:
    """
    Register a user via API and mark TOTP as verified.

    Returns (username, password, plain_totp_secret).
    """
    username = "testuser"
    password = "testpass123"

    resp = await app_client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 201, f"Registration failed: {resp.json()}"
    totp_secret = resp.json()["totp_secret"]

    # Mark TOTP as verified so login works without going through enrollment
    await db_session.execute(update(TOTPSecret).values(is_verified=True))
    await db_session.commit()

    return username, password, totp_secret


@pytest.fixture
async def admin_user(app_client, db_session) -> tuple[str, str, str]:
    """
    Register an admin user via API; set is_admin=True and TOTP verified directly.

    Returns (username, password, plain_totp_secret).
    """
    username = "adminuser"
    password = "adminpass123"

    resp = await app_client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 201, f"Admin registration failed: {resp.json()}"
    totp_secret = resp.json()["totp_secret"]

    await db_session.execute(
        update(User).where(User.username == username).values(is_admin=True)
    )
    await db_session.execute(update(TOTPSecret).values(is_verified=True))
    await db_session.commit()

    return username, password, totp_secret


# ── Auth header helpers ───────────────────────────────────────────────────────


async def get_access_token(
    client: AsyncClient,
    username: str,
    password: str,
    totp_secret: str,
) -> str:
    """
    Perform full login flow and return a full-access JWT.

    Handles the case where the first TOTP verify is an enrollment confirmation
    (returns {success: true}) by running the login flow a second time.
    """
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.json()}"
    auth_token = login_resp.json()["auth_token"]

    code = pyotp.TOTP(totp_secret).now()
    verify_resp = await client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_code": code},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert verify_resp.status_code == 200, f"TOTP verify failed: {verify_resp.json()}"
    body = verify_resp.json()

    if "access_token" in body:
        return body["access_token"]

    # Enrollment context returned {success: true} — re-run login to get access token
    login_resp2 = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp2.status_code == 200, f"Second login failed: {login_resp2.json()}"
    auth_token2 = login_resp2.json()["auth_token"]

    code2 = pyotp.TOTP(totp_secret).now()
    verify_resp2 = await client.post(
        "/api/v1/auth/totp/verify",
        json={"totp_code": code2},
        headers={"Authorization": f"Bearer {auth_token2}"},
    )
    assert verify_resp2.status_code == 200, f"Second TOTP verify failed: {verify_resp2.json()}"
    return verify_resp2.json()["access_token"]


@pytest.fixture
async def auth_headers(app_client, registered_user) -> dict[str, str]:
    """Authorization headers with a valid full-access JWT for testuser."""
    username, password, totp_secret = registered_user
    token = await get_access_token(app_client, username, password, totp_secret)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def admin_auth_headers(app_client, admin_user) -> dict[str, str]:
    """Authorization headers with a valid full-access JWT for the admin user."""
    username, password, totp_secret = admin_user
    token = await get_access_token(app_client, username, password, totp_secret)
    return {"Authorization": f"Bearer {token}"}


# ── Token factories ───────────────────────────────────────────────────────────


def make_access_token(
    user_id: str,
    is_admin: bool = False,
    ttl_seconds: int = 86400,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Craft a valid full-access JWT for a given user_id."""
    payload = {
        "sub": user_id,
        "scope": "full",
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def make_intermediate_token(
    user_id: str,
    ttl_seconds: int = 300,
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Craft a valid intermediate (TOTP-verify scope) JWT."""
    payload = {
        "sub": user_id,
        "scope": "totp_verify",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def make_expired_token(
    user_id: str,
    scope: str = "full",
    secret: str = TEST_JWT_SECRET,
) -> str:
    """Craft an already-expired JWT."""
    payload = {
        "sub": user_id,
        "scope": scope,
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")
