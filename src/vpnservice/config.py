from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "VPN_"}

    # Encryption key for TOTP secrets (Fernet)
    secret_key: str = "CHANGE-ME-generate-with-Fernet.generate_key()"

    # JWT
    jwt_secret: str = "CHANGE-ME-use-a-random-string"
    jwt_access_ttl: int = 86400  # 24 hours
    jwt_intermediate_ttl: int = 300  # 5 minutes

    # WireGuard
    wg_endpoint: str = "vpn.example.com:51820"
    wg_subnet: str = "10.10.0.0/24"
    wg_interface: str = "wg0"
    wg_listen_port: int = 51820
    wg_private_key_path: str = "/data/wg_private.key"

    # Database
    db_path: str = "/data/vpnservice.db"

    # Admin seeding (optional)
    admin_username: str | None = None
    admin_password: str | None = None

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
