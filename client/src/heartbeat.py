import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

from client.src.device_info import check_wda_health, get_battery_level

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
        self._udid_map: dict[str, str] = {}  # device_uid -> full udid

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
            udid = self._udid_map.get(dev.device_uid, "")
            battery = None
            if is_healthy:
                usb_available = await self._is_usb_connected(udid) if udid else False
                battery = await get_battery_level(
                    dev.wda_url, udid if usb_available else ""
                )
            device_statuses.append({
                "device_uid": dev.device_uid,
                "status": "online" if is_healthy else "error",
                "battery_level": battery,
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

    @staticmethod
    async def _is_usb_connected(udid: str) -> bool:
        """Quick check whether device is still USB-connected."""
        try:
            from pymobiledevice3.usbmux import list_devices
            devs = await list_devices()
            return any(d.serial == udid and d.connection_type == "USB" for d in devs)
        except Exception:
            return False

    def add_device(self, device, udid: str = ""):
        for i, d in enumerate(self.devices):
            if d.device_uid == device.device_uid:
                self.devices[i] = device
                if udid:
                    self._udid_map[device.device_uid] = udid
                return
        self.devices.append(device)
        logger.info("Heartbeat now tracking %d device(s)", len(self.devices))
        if udid:
            self._udid_map[device.device_uid] = udid
