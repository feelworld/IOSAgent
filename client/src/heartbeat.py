import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

from client.src.device_info import check_wda_health, get_battery_level

logger = logging.getLogger(__name__)


class HeartbeatSender:
    MAX_CONSECUTIVE_ERRORS = 3

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
        self._error_counts: dict[str, int] = {}  # device_uid -> consecutive error count

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
        to_remove = []

        for dev in list(self.devices):
            is_healthy = await check_wda_health(dev.wda_url)
            uid = dev.device_uid
            udid = self._udid_map.get(uid, "")
            battery = None

            if is_healthy:
                self._error_counts[uid] = 0
                usb_available = await self._is_usb_connected(udid) if udid else False
                battery = await get_battery_level(
                    dev.wda_url, udid if usb_available else ""
                )
            else:
                self._error_counts[uid] = self._error_counts.get(uid, 0) + 1
                if self._error_counts[uid] >= self.MAX_CONSECUTIVE_ERRORS:
                    logger.warning("Device %s failed %d consecutive heartbeats — auto-removing",
                                   uid, self._error_counts[uid])
                    to_remove.append(uid)
                    continue

            device_statuses.append({
                "device_uid": uid,
                "status": "online" if is_healthy else "error",
                "battery_level": battery,
                "network_type": None,
                "appstore_logged_in": None,
                "current_task_id": None,
            })

        for uid in to_remove:
            self.remove_device(uid)

        if not device_statuses:
            return

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

    def remove_device(self, device_uid: str):
        self.devices = [d for d in self.devices if d.device_uid != device_uid]
        self._udid_map.pop(device_uid, None)
        self._error_counts.pop(device_uid, None)
        logger.info("Device %s removed from heartbeat, tracking %d device(s)",
                     device_uid, len(self.devices))
        asyncio.ensure_future(self._send_offline_notice(device_uid))

    async def _send_offline_notice(self, device_uid: str):
        """Immediately tell the server this device is offline."""
        try:
            message = {
                "type": "heartbeat",
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "machine_id": self.machine_id,
                    "devices": [{
                        "device_uid": device_uid,
                        "status": "offline",
                        "battery_level": None,
                        "network_type": None,
                        "appstore_logged_in": None,
                        "current_task_id": None,
                    }],
                },
            }
            await self.send_fn(message)
            logger.info("Sent offline notice for %s", device_uid)
        except Exception as e:
            logger.warning("Failed to send offline notice for %s: %s", device_uid, e)
