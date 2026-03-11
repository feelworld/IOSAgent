import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware

from server.src.api.auth import router as auth_router
from server.src.api.devices import router as devices_router
from server.src.api.tasks import router as tasks_router
from server.src.api.device_groups import router as device_groups_router
from server.src.api.apple_accounts import router as apple_accounts_router
from server.src.api.scripts import router as scripts_router
from server.src.api.strategies import router as strategies_router
from server.src.api.dashboard import router as dashboard_router
from server.src.api.health import router as health_router
from server.src.api.config import router as config_router
from server.src.middleware.audit import AuditMiddleware
from server.src.db import close_db, init_db
from server.src.services.device_manager import check_offline_devices
from server.src.services.strategy_engine import monitor_effectiveness_loop
from server.src.ws.admin_handler import admin_ws_endpoint
from server.src.ws.client_handler import client_ws_endpoint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OFFLINE_CHECK_INTERVAL = 30
EFFECTIVENESS_MONITOR_INTERVAL = 60


async def _offline_check_loop():
    """Periodically mark stale devices as offline."""
    while True:
        try:
            uids = await check_offline_devices()
            if uids:
                logger.info(f"Offline check: marked {len(uids)} device(s) offline")
        except Exception as e:
            logger.error(f"Offline check error: {e}")
        await asyncio.sleep(OFFLINE_CHECK_INTERVAL)


async def _effectiveness_monitor_loop():
    """Periodically check strategy effectiveness and alert on decline."""
    while True:
        try:
            await monitor_effectiveness_loop()
        except Exception as e:
            logger.error(f"Effectiveness monitor error: {e}")
        await asyncio.sleep(EFFECTIVENESS_MONITOR_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    offline_task = asyncio.create_task(_offline_check_loop())
    monitor_task = asyncio.create_task(_effectiveness_monitor_loop())
    yield
    offline_task.cancel()
    monitor_task.cancel()
    await close_db()


app = FastAPI(
    title="iOS Ranking System API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(AuditMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(devices_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(device_groups_router, prefix="/api/v1")
app.include_router(apple_accounts_router, prefix="/api/v1")
app.include_router(scripts_router, prefix="/api/v1")
app.include_router(strategies_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(health_router)


@app.websocket("/ws/client/{machine_id}")
async def ws_client(websocket: WebSocket, machine_id: str, token: str = Query(...)):
    await client_ws_endpoint(websocket, machine_id, token)


@app.websocket("/ws/admin")
async def ws_admin(websocket: WebSocket, token: str = Query(...)):
    await admin_ws_endpoint(websocket, token)


@app.get("/")
async def root():
    return {"message": "iOS Ranking System API", "version": "0.1.0"}
