from __future__ import annotations

import base64
from io import BytesIO

import pyotp
import qrcode
import qrcode.image.pure
from cryptography.fernet import Fernet, InvalidToken

from vpnservice.config import Settings


def _get_fernet(settings: Settings) -> Fernet:
    """Construct a Fernet instance from the application secret key."""
    key = settings.secret_key
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_secret(plain_secret: str, settings: Settings) -> str:
    """Encrypt a plaintext TOTP secret for storage in the database."""
    fernet = _get_fernet(settings)
    return fernet.encrypt(plain_secret.encode()).decode()


def decrypt_secret(encrypted_secret: str, settings: Settings) -> str:
    """
    Decrypt a stored TOTP secret.

    Raises ValueError if the ciphertext is invalid or the key has changed.
    """
    fernet = _get_fernet(settings)
    try:
        return fernet.decrypt(encrypted_secret.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt TOTP secret") from exc


def _generate_qr_base64(totp_uri: str) -> str:
    """Render a TOTP provisioning URI as a base64-encoded PNG QR code."""
    qr = qrcode.QRCode()
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def generate_totp_secret(
    username: str, settings: Settings
) -> tuple[str, str, str, str]:
    """
    Generate a new TOTP secret for a user.

    Returns a 4-tuple of:
        plain_secret    — raw Base32 secret (shown once to the user)
        totp_uri        — otpauth:// URI for the authenticator app
        qr_base64       — base64-encoded PNG QR code
        encrypted_secret — Fernet-encrypted secret, safe for DB storage
    """
    plain_secret = pyotp.random_base32()
    totp = pyotp.TOTP(plain_secret)
    totp_uri = totp.provisioning_uri(name=username, issuer_name="VPNService")
    qr_base64 = _generate_qr_base64(totp_uri)
    encrypted_secret = encrypt_secret(plain_secret, settings)
    return plain_secret, totp_uri, qr_base64, encrypted_secret


def verify_totp_code(
    encrypted_secret: str, totp_code: str, settings: Settings
) -> bool:
    """
    Verify a TOTP code against an encrypted secret.

    Allows a ±1 time-step window (30 s each side) to tolerate clock drift
    between the client device and the server.
    """
    plain_secret = decrypt_secret(encrypted_secret, settings)
    totp = pyotp.TOTP(plain_secret)
    return totp.verify(totp_code, valid_window=1)
