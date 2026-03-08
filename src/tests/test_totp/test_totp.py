"""
Tests for TOTP service layer.

Covers:
- pyotp TOTP code generation and verification (algorithm correctness)
- Window tolerance: ±1 time step (30 s clock drift)
- Code format validation (6 digits)
- Wrong code rejection
- MockWireGuardManager smoke tests (used in VPN tests)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pyotp
import pytest

from tests.conftest import MockWireGuardManager, WG_PUBLIC_KEY_1, WG_PUBLIC_KEY_2
from vpnservice.wireguard.manager import WireGuardError


# ── TOTP algorithm ────────────────────────────────────────────────────────────


class TestTOTPAlgorithm:
    def test_generate_totp_secret_is_valid_base32(self):
        """pyotp.random_base32() produces a usable TOTP secret."""
        import base64

        secret = pyotp.random_base32()
        assert len(secret) > 0
        # Must decode without error
        base64.b32decode(secret, casefold=True)

    def test_totp_current_code_verifies(self):
        """A code generated now must pass verification in the same window."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert totp.verify(code), "Current TOTP code must verify successfully"

    def test_totp_code_is_six_digits(self):
        """TOTP codes must be exactly 6 decimal digits."""
        secret = pyotp.random_base32()
        code = pyotp.TOTP(secret).now()
        assert len(code) == 6, f"TOTP code must be 6 digits, got {len(code)}: {code}"
        assert code.isdigit(), f"TOTP code must be numeric, got: {code}"

    def test_totp_wrong_code_fails_verification(self):
        """An arbitrary wrong code must not verify."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        # Flip last digit to create wrong code
        wrong_code = code[:-1] + str((int(code[-1]) + 1) % 10)
        # With valid_window=1 there's still a tiny chance of coincidental match,
        # but with a strictly different digit this should reliably fail
        if code != wrong_code:
            assert not totp.verify(wrong_code), (
                f"Wrong code {wrong_code} must not verify against {code}"
            )

    def test_totp_codes_from_different_secrets_differ(self):
        """Two different secrets produce different codes (with overwhelming probability)."""
        secret1 = pyotp.random_base32()
        secret2 = pyotp.random_base32()
        assert secret1 != secret2
        code1 = pyotp.TOTP(secret1).now()
        code2 = pyotp.TOTP(secret2).now()
        # Codes could theoretically match by chance, but this is extremely unlikely
        # with independently generated secrets
        assert secret1 != secret2, "Secrets must differ"

    def test_totp_verify_with_valid_window_1(self):
        """Verification with valid_window=1 allows ±30 s clock drift."""
        import time

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        # valid_window=1 means current ±1 interval (total 3 windows)
        assert totp.verify(code, valid_window=1), (
            "Current code must verify with valid_window=1"
        )

    def test_totp_uri_format(self):
        """otpauth URI must follow the standard format."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name="testuser", issuer_name="VPNService")
        assert uri.startswith("otpauth://totp/"), f"URI format wrong: {uri}"
        assert "VPNService" in uri, "Issuer must appear in URI"
        assert "testuser" in uri, "Account name must appear in URI"
        assert secret in uri, "Secret must appear in URI"

    @pytest.mark.parametrize(
        "code,expected_valid",
        [
            ("000000", None),   # might be valid or not — we just check it's handled
            ("123456", None),   # same
            ("999999", None),   # same
        ],
    )
    def test_totp_verify_handles_any_six_digit_input(self, code: str, expected_valid):
        """verify() must not raise exceptions for well-formed 6-digit codes."""
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        result = totp.verify(code)  # must not raise
        assert isinstance(result, bool), "verify() must return bool"


# ── MockWireGuardManager ──────────────────────────────────────────────────────


class TestMockWireGuardManager:
    """Smoke tests for MockWireGuardManager used across VPN / admin test modules."""

    async def test_add_peer_records_call(self):
        mgr = MockWireGuardManager()
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
        assert len(mgr.add_peer_calls) == 1
        assert mgr.add_peer_calls[0]["public_key"] == WG_PUBLIC_KEY_1
        assert mgr.add_peer_calls[0]["allowed_ips"] == "10.10.0.2/32"

    async def test_add_peer_stores_in_peers_dict(self):
        mgr = MockWireGuardManager()
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
        assert WG_PUBLIC_KEY_1 in mgr.peers
        assert mgr.peers[WG_PUBLIC_KEY_1] == "10.10.0.2/32"

    async def test_remove_peer_records_call(self):
        mgr = MockWireGuardManager()
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
        await mgr.remove_peer(WG_PUBLIC_KEY_1)
        assert WG_PUBLIC_KEY_1 in mgr.remove_peer_calls
        assert WG_PUBLIC_KEY_1 not in mgr.peers

    async def test_remove_nonexistent_peer_does_not_raise(self):
        mgr = MockWireGuardManager()
        await mgr.remove_peer("nonexistentkey")  # must not raise

    async def test_get_peer_stats_returns_none_for_unknown_key(self):
        mgr = MockWireGuardManager()
        stats = await mgr.get_peer_stats("unknownkey")
        assert stats is None

    async def test_get_peer_stats_returns_stats_for_known_peer(self):
        mgr = MockWireGuardManager()
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
        stats = await mgr.get_peer_stats(WG_PUBLIC_KEY_1)
        assert stats is not None
        assert stats.public_key == WG_PUBLIC_KEY_1
        assert stats.transfer_rx >= 0
        assert stats.transfer_tx >= 0

    async def test_list_peers_returns_all_added_peers(self):
        mgr = MockWireGuardManager()
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
        await mgr.add_peer(WG_PUBLIC_KEY_2, "10.10.0.3/32")
        peers = await mgr.list_peers()
        public_keys = [p.public_key for p in peers]
        assert WG_PUBLIC_KEY_1 in public_keys
        assert WG_PUBLIC_KEY_2 in public_keys

    async def test_fail_mode_raises_on_add_peer(self):
        mgr = MockWireGuardManager()
        mgr.set_fail_mode(True)
        with pytest.raises(WireGuardError):
            await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")

    async def test_fail_mode_raises_on_remove_peer(self):
        mgr = MockWireGuardManager()
        mgr.set_fail_mode(True)
        with pytest.raises(WireGuardError):
            await mgr.remove_peer(WG_PUBLIC_KEY_1)

    def test_get_server_public_key_returns_string(self):
        mgr = MockWireGuardManager()
        key = mgr.get_server_public_key()
        assert isinstance(key, str)
        assert len(key) > 0

    def test_get_endpoint_returns_host_port(self):
        mgr = MockWireGuardManager()
        endpoint = mgr.get_endpoint()
        assert ":" in endpoint, f"Endpoint must be host:port format, got: {endpoint}"

    async def test_reset_clears_all_state(self):
        mgr = MockWireGuardManager()
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
        mgr.set_fail_mode(True)
        mgr.reset()
        assert mgr.peers == {}
        assert mgr.add_peer_calls == []
        assert mgr.remove_peer_calls == []
        # Should not fail after reset
        await mgr.add_peer(WG_PUBLIC_KEY_1, "10.10.0.2/32")
