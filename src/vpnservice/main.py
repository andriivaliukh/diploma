import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from vpnservice import __version__
from vpnservice.admin.router import router as admin_router
from vpnservice.admin.service import seed_admin_user
from vpnservice.auth.router import router as auth_router
from vpnservice.config import get_settings
from vpnservice.database import init_db
from vpnservice.tasks.cleanup import start_cleanup_task
from vpnservice.totp.router import router as totp_router
from vpnservice.vpn.router import devices_router, health_router, router as vpn_router, set_wg_manager
from vpnservice.wireguard.manager import WireGuardManager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_admin_user(get_settings())
    wg = WireGuardManager()
    try:
        await wg.initialize()
    except Exception as exc:
        logger.warning("WireGuard init failed (running without tunnel): %s", exc)
    set_wg_manager(wg)
    cleanup_task = start_cleanup_task(wg)
    yield
    cleanup_task.cancel()


app = FastAPI(
    title="VPN Service with 2FA",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(totp_router, prefix="/api/v1/auth/totp", tags=["totp"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(vpn_router, prefix="/api/v1/vpn", tags=["vpn"])
app.include_router(devices_router, prefix="/api/v1/devices", tags=["devices"])
app.include_router(health_router, prefix="/api/v1", tags=["health"])
