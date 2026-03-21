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
    wifi_ip: Optional[str] = None


async def collect_device_info(wda_url: str, device_uid: str) -> DeviceInfo:
    """Query WDA /status and /wda/batteryInfo endpoints to gather device info."""
    info = DeviceInfo(device_uid=device_uid, model="", ios_version="")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(
                f"{wda_url}/status",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                value = data.get("value", {})
                os_info = value.get("os", {})
                info.ios_version = os_info.get("version", "")
                info.wifi_ip = value.get("ios", {}).get("ip", "")

                raw_device = value.get("device", {})
                if isinstance(raw_device, dict):
                    info.model = raw_device.get("model", "") or raw_device.get("name", "")
                elif isinstance(raw_device, str) and raw_device not in ("Unknown", ""):
                    info.model = raw_device
        except Exception as e:
            logger.error("Failed to collect device info from %s: %s", wda_url, e)

        for endpoint in ("/wda/batteryInfo", "/wda/device/info"):
            try:
                async with session.get(
                    f"{wda_url}{endpoint}",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    level = data.get("value", {}).get("level")
                    if level is not None:
                        info.battery_level = int(level * 100)
                        break
            except Exception:
                continue

    return info


async def get_battery_level(wda_url: str, udid: str = "") -> Optional[int]:
    """Get battery level. Tries lockdown first (more reliable), then WDA."""
    if udid:
        try:
            level = await _get_battery_via_lockdown(udid)
            if level is not None:
                return level
        except Exception:
            pass

    try:
        async with aiohttp.ClientSession() as session:
            for endpoint in ("/wda/batteryInfo", "/wda/device/info"):
                try:
                    async with session.get(
                        f"{wda_url}{endpoint}",
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json()
                        value = data.get("value", {})
                        level = value.get("level")
                        if level is not None:
                            return int(level * 100)
                except Exception:
                    continue
    except Exception:
        pass
    return None


async def _get_battery_via_lockdown(udid: str) -> Optional[int]:
    """Get battery level directly from device via DiagnosticsService."""
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.diagnostics import DiagnosticsService
    ld = await create_using_usbmux(serial=udid)
    ds = DiagnosticsService(lockdown=ld)
    await ds.connect()
    info = await ds.get_battery()
    cap = info.get("CurrentCapacity")
    if cap is not None:
        return int(cap)
    return None


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
