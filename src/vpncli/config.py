"""CLI configuration and token storage.

Manages persistent state for the vpncli tool, stored under ~/.vpncli/.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".vpncli"
TOKENS_FILE = CONFIG_DIR / "tokens.json"


def _ensure_config_dir() -> None:
    """Create the config directory if it does not exist."""
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)


def save_token(server: str, access_token: str, expires_at: datetime) -> None:
    """Persist an access token for a given server URL.

    Args:
        server: The server base URL used as the storage key.
        access_token: The JWT access token string.
        expires_at: UTC datetime when the token expires.
    """
    _ensure_config_dir()

    tokens: dict = {}
    if TOKENS_FILE.exists():
        try:
            tokens = json.loads(TOKENS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            tokens = {}

    tokens[server] = {
        "access_token": access_token,
        "expires_at": expires_at.isoformat(),
    }

    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
    TOKENS_FILE.chmod(0o600)


def load_token(server: str) -> Optional[str]:
    """Load a valid (non-expired) access token for a given server URL.

    Args:
        server: The server base URL to look up.

    Returns:
        The access token string, or None if not found or expired.
    """
    if not TOKENS_FILE.exists():
        return None

    try:
        tokens: dict = json.loads(TOKENS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    entry = tokens.get(server)
    if not entry:
        return None

    try:
        expires_at = datetime.fromisoformat(entry["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None

    if datetime.now(timezone.utc) >= expires_at:
        return None

    return entry.get("access_token")


def clear_token(server: str) -> None:
    """Remove the stored token for a given server URL.

    Args:
        server: The server base URL whose token should be removed.
    """
    if not TOKENS_FILE.exists():
        return

    try:
        tokens: dict = json.loads(TOKENS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return

    tokens.pop(server, None)
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))
