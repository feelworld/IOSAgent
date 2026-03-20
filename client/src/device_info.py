import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    device_uid: str
    model: str
    ios_version: str
    battery_level: Optional[int] = None
    network_type: Optional[str] = None
    screen_size: Optional[str] = None


async def collect_device_info(wda_url: str, device_uid: str) -> DeviceInfo:
    """Query WDA /status endpoint to gather device info."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{wda_url}/status",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                value = data.get("value", {})
                os_info = value.get("os", {})
                raw_device = value.get("device", {})
                device_data = raw_device if isinstance(raw_device, dict) else {}
                device_name = raw_device if isinstance(raw_device, str) else device_data.get("model", "Unknown")

                return DeviceInfo(
                    device_uid=device_uid,
                    model=device_data.get("model", None) or device_name or "Unknown",
                    ios_version=os_info.get("version", "Unknown"),
                    battery_level=None,
                    network_type=None,
                    screen_size=None,
                )
        except Exception as e:
            logger.error("Failed to collect device info from %s: %s", wda_url, e)
            return DeviceInfo(
                device_uid=device_uid,
                model="Unknown",
                ios_version="Unknown",
            )


async def check_wda_health(wda_url: str) -> bool:
    """Check if WDA is reachable and responsive."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{wda_url}/status",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
    except Exception:
        return False
