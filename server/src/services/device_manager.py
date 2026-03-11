import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from beanie import PydanticObjectId
from beanie.operators import In

from server.src.models.device import Device, DeviceStatus
from server.src.models.companion import CompanionMachine, CompanionStatus

logger = logging.getLogger(__name__)


async def register_device(
    device_uid: str,
    model: str,
    ios_version: str,
    wda_url: str,
    companion_id: str,
) -> Device:
    """Register a new device or update existing one on reconnect."""
    device = await Device.find_one(Device.device_uid == device_uid)
    now = datetime.now(timezone.utc)
    if device:
        device.model = model
        device.ios_version = ios_version
        device.wda_url = wda_url
        device.companion_id = companion_id
        device.status = DeviceStatus.ONLINE
        device.last_heartbeat = now
        await device.save()
        logger.info(f"Device re-registered: {device_uid}")
    else:
        device = Device(
            device_uid=device_uid,
            model=model,
            ios_version=ios_version,
            wda_url=wda_url,
            companion_id=companion_id,
            status=DeviceStatus.ONLINE,
            last_heartbeat=now,
            registered_at=now,
        )
        await device.insert()
        logger.info(f"New device registered: {device_uid}")
    return device


async def register_companion(
    machine_id: str,
    device_ids: list[PydanticObjectId] | None = None,
    ip_address: str | None = None,
) -> CompanionMachine:
    """Register or update a companion machine."""
    companion = await CompanionMachine.find_one(
        CompanionMachine.machine_id == machine_id
    )
    now = datetime.now(timezone.utc)
    if companion:
        companion.status = CompanionStatus.ONLINE
        companion.last_heartbeat = now
        if device_ids is not None:
            companion.managed_device_ids = device_ids
        if ip_address:
            companion.ip_address = ip_address
        await companion.save()
    else:
        companion = CompanionMachine(
            machine_id=machine_id,
            status=CompanionStatus.ONLINE,
            managed_device_ids=device_ids or [],
            last_heartbeat=now,
            registered_at=now,
            ip_address=ip_address,
        )
        await companion.insert()
    return companion


async def update_heartbeat(
    device_uid: str,
    status: str,
    battery_level: int | None = None,
    network_type: str | None = None,
    current_task_id: str | None = None,
) -> Optional[Device]:
    """Update device heartbeat and status."""
    device = await Device.find_one(Device.device_uid == device_uid)
    if not device:
        logger.warning(f"Heartbeat for unknown device: {device_uid}")
        return None
    try:
        device.status = DeviceStatus(status)
    except ValueError:
        pass
    device.last_heartbeat = datetime.now(timezone.utc)
    if battery_level is not None:
        device.battery_level = battery_level
    if network_type is not None:
        device.network_type = network_type
    await device.save()
    return device


async def check_offline_devices(timeout_seconds: int = 90) -> list[str]:
    """Background task: mark devices offline if heartbeat timeout exceeded."""
    threshold = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    stale_devices = await Device.find(
        In(Device.status, [DeviceStatus.ONLINE, DeviceStatus.BUSY]),
        Device.last_heartbeat < threshold,
    ).to_list()

    offline_device_uids: list[str] = []
    for device in stale_devices:
        device.status = DeviceStatus.OFFLINE
        await device.save()
        offline_device_uids.append(device.device_uid)
        logger.info(f"Device marked offline (timeout): {device.device_uid}")

    return offline_device_uids


async def get_device_stats() -> dict:
    """Get aggregated device statistics."""
    total = await Device.count()
    online = await Device.find(Device.status == DeviceStatus.ONLINE).count()
    offline = await Device.find(Device.status == DeviceStatus.OFFLINE).count()
    busy = await Device.find(Device.status == DeviceStatus.BUSY).count()
    error = await Device.find(Device.status == DeviceStatus.ERROR).count()
    return {
        "total": total,
        "online": online,
        "offline": offline,
        "busy": busy,
        "error": error,
        "online_rate": round(online / total, 3) if total > 0 else 0,
    }
