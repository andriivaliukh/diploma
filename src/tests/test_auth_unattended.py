"""Tests for vpncli unattended (CLI-flag) auth flows.

Covers the to-be-implemented flag-based mode that lets bench scripts drive
register/login without a TTY:
- _compute_totp_from_secret: stdlib RFC 6238 TOTP helper
- register_flow(password=, auto_totp=True): no interactive prompts
- login_flow(password=, totp_secret=): no interactive prompts
- Interactive regression: existing prompt paths still fire without the new flags
"""
from unittest.mock import MagicMock, patch

import pytest

from vpncli.auth import (
    _compute_totp_from_secret,
    login_flow,
    register_flow,
)


# ---------------------------------------------------------------------------
# _compute_totp_from_secret — RFC 6238 known vectors
# ---------------------------------------------------------------------------


def test_totp_vector_t59():
    assert _compute_totp_from_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", t=59) == "287082"


def test_totp_vector_t1111111109():
    assert _compute_totp_from_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", t=1111111109) == "081804"


# ---------------------------------------------------------------------------
# register_flow — auto-TOTP mode (password= + auto_totp=True)
# ---------------------------------------------------------------------------


def test_register_flow_auto_totp_no_prompts():
    """password= + auto_totp=True must not trigger any interactive prompts."""
    client = MagicMock()
    client.register.return_value = {
        "totp_uri": "otpauth://totp/test",
        "totp_secret": "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ",
        "auth_token": "intermediate-token",
    }
    client.verify_totp.return_value = {}

    def _fail(*args, **kwargs):
        raise AssertionError("interactive prompt must not be called in auto mode")

    with patch("getpass.getpass", side_effect=_fail), \
         patch("typer.prompt", side_effect=_fail):
        register_flow(client, "https://example.com", "user1",
                      password="secret", auto_totp=True)


def test_register_flow_auto_totp_uses_server_secret():
    """verify_totp receives the code computed from the server-returned secret."""
    server_secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    fixed_t = 1_000_000_000.0
    client = MagicMock()
    client.register.return_value = {
        "totp_uri": "otpauth://totp/test",
        "totp_secret": server_secret,
        "auth_token": "tok",
    }
    client.verify_totp.return_value = {}

    with patch("getpass.getpass", side_effect=AssertionError("no prompt")), \
         patch("typer.prompt", side_effect=AssertionError("no prompt")), \
         patch("time.time", return_value=fixed_t):
        register_flow(client, "https://example.com", "user1",
                      password="pw", auto_totp=True)

    expected = _compute_totp_from_secret(server_secret, t=fixed_t)
    actual = client.verify_totp.call_args[0][2]
    assert actual == expected


def test_register_flow_auto_totp_echoes_secret_to_stderr(capsys):
    """auto_totp=True emits 'TOTP_SECRET=<base32>' to stderr."""
    server_secret = "JBSWY3DPEHPK3PXP"
    client = MagicMock()
    client.register.return_value = {
        "totp_uri": "otpauth://totp/test",
        "totp_secret": server_secret,
        "auth_token": "tok",
    }
    client.verify_totp.return_value = {}

    with patch("getpass.getpass", side_effect=AssertionError("no prompt")), \
         patch("typer.prompt", side_effect=AssertionError("no prompt")):
        register_flow(client, "https://example.com", "user1",
                      password="pw", auto_totp=True)

    assert f"TOTP_SECRET={server_secret}" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# login_flow — unattended mode (password= + totp_secret=)
# ---------------------------------------------------------------------------


def test_login_flow_totp_secret_no_prompts():
    """password= + totp_secret= must not trigger any interactive prompts."""
    client = MagicMock()
    client.login.return_value = {"auth_token": "intermediate"}
    client.verify_totp.return_value = {"access_token": "full-token", "expires_in": 86400}

    def _fail(*args, **kwargs):
        raise AssertionError("interactive prompt must not be called when flags are set")

    with patch("getpass.getpass", side_effect=_fail), \
         patch("typer.prompt", side_effect=_fail), \
         patch("vpncli.auth.save_token"):
        login_flow(client, "https://example.com", "user1",
                   password="pw", totp_secret="GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")


def test_login_flow_totp_secret_uses_computed_code():
    """verify_totp receives the code from _compute_totp_from_secret(totp_secret)."""
    server_secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    fixed_t = 1_000_000_000.0
    client = MagicMock()
    client.login.return_value = {"auth_token": "tok"}
    client.verify_totp.return_value = {"access_token": "full", "expires_in": 86400}

    with patch("getpass.getpass", side_effect=AssertionError("no prompt")), \
         patch("typer.prompt", side_effect=AssertionError("no prompt")), \
         patch("vpncli.auth.save_token"), \
         patch("time.time", return_value=fixed_t):
        login_flow(client, "https://example.com", "user1",
                   password="pw", totp_secret=server_secret)

    expected = _compute_totp_from_secret(server_secret, t=fixed_t)
    actual = client.verify_totp.call_args[0][2]
    assert actual == expected


# ---------------------------------------------------------------------------
# Interactive regression — no new flags → existing prompts still fire
# ---------------------------------------------------------------------------


def test_register_flow_interactive_regression():
    """Without password=/auto_totp=, getpass fires twice and typer.prompt fires once."""
    client = MagicMock()
    client.register.return_value = {
        "totp_uri": "otpauth://totp/test",
        "totp_secret": "JBSWY3DPEHPK3PXP",
        "auth_token": "tok",
    }
    client.verify_totp.return_value = {}

    with patch("getpass.getpass", return_value="interactivepass") as mock_gp, \
         patch("typer.prompt", return_value="123456") as mock_tp:
        register_flow(client, "https://example.com", "user1")

    assert mock_gp.call_count == 2
    assert mock_tp.called


def test_login_flow_interactive_regression():
    """Without password=/totp_secret=, getpass fires once and typer.prompt fires once."""
    client = MagicMock()
    client.login.return_value = {"auth_token": "tok"}
    client.verify_totp.return_value = {"access_token": "full", "expires_in": 86400}

    with patch("getpass.getpass", return_value="interactivepass") as mock_gp, \
         patch("typer.prompt", return_value="123456") as mock_tp, \
         patch("vpncli.auth.save_token"):
        login_flow(client, "https://example.com", "user1")

    assert mock_gp.call_count == 1
    assert mock_tp.called
