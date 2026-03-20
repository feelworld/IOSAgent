import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

from client.src.device_info import check_wda_health

logger = logging.getLogger(__name__)


class HeartbeatSender:
    def __init__(
        self,
        machine_id: str,
        devices: list,
        send_fn: Callable[[dict], Awaitable[None]],
        interval: int = 30,
    ):
        self.machine_id = machine_id
        self.devices = devices
        self.send_fn = send_fn
        self.interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat started (interval=%ds)", self.interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Heartbeat stopped")

    async def _loop(self):
        while self._running:
            try:
                await self._send_heartbeat()
            except Exception as e:
                logger.error("Heartbeat error: %s", e)
            await asyncio.sleep(self.interval)

    async def _send_heartbeat(self):
        device_statuses = []
        for dev in self.devices:
            is_healthy = await check_wda_health(dev.wda_url)
            device_statuses.append({
                "device_uid": dev.device_uid,
                "status": "online" if is_healthy else "error",
                "battery_level": None,
                "network_type": None,
                "appstore_logged_in": None,
                "current_task_id": None,
            })

        message = {
            "type": "heartbeat",
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "machine_id": self.machine_id,
                "devices": device_statuses,
            },
        }
        await self.send_fn(message)
        logger.debug("Heartbeat sent for %d devices", len(device_statuses))

    def update_interval(self, new_interval: int):
        self.interval = new_interval
        logger.info("Heartbeat interval updated to %ds", new_interval)

    def add_device(self, device):
        if not any(d.device_uid == device.device_uid for d in self.devices):
            self.devices.append(device)
            logger.info("Heartbeat now tracking %d device(s)", len(self.devices))
