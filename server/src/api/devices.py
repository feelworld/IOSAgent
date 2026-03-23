import logging
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query

from server.src.api.auth import get_current_user
from server.src.models.device import Device, DeviceStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("")
async def list_devices(
    status: Optional[str] = Query(None),
    group_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort: str = Query("last_heartbeat:desc"),
    _user=Depends(get_current_user),
):
    query = Device.find()
    if status:
        query = Device.find(Device.status == DeviceStatus(status))
    if group_id:
        query = Device.find(Device.group_ids == PydanticObjectId(group_id))

    sort_field, sort_dir = sort.split(":") if ":" in sort else (sort, "desc")
    sort_expr = f"-{sort_field}" if sort_dir == "desc" else f"+{sort_field}"

    total = await query.count()
    items = (
        await query.sort(sort_expr).skip((page - 1) * size).limit(size).to_list()
    )

    return {
        "code": 0,
        "message": "success",
        "data": {
            "items": [await _serialize_device(d) for d in items],
            "total": total,
            "page": page,
            "size": size,
        },
    }


@router.get("/stats")
async def device_stats(_user=Depends(get_current_user)):
    from server.src.services.device_manager import get_device_stats

    stats = await get_device_stats()
    return {"code": 0, "message": "success", "data": stats}


@router.get("/{device_id}")
async def get_device(device_id: str, _user=Depends(get_current_user)):
    device = await Device.get(PydanticObjectId(device_id))
    if not device:
        return {"code": 40401, "message": "Device not found", "data": None}
    return {"code": 0, "message": "success", "data": await _serialize_device(device)}


async def _serialize_device(device: Device) -> dict:
    current_apple_email = None
    if device.current_apple_id:
        from server.src.models.apple_account import AppleAccount
        acct = await AppleAccount.get(device.current_apple_id)
        if acct:
            current_apple_email = acct.email

    if not current_apple_email:
        from server.src.models.apple_account import AppleAccount, AppleAccountStatus
        acct = await AppleAccount.find_one(
            AppleAccount.bound_device_id == device.id,
            AppleAccount.status == AppleAccountStatus.ACTIVE,
        )
        if acct:
            current_apple_email = acct.email

    return {
        "id": str(device.id),
        "device_uid": device.device_uid,
        "name": device.name,
        "model": device.model,
        "ios_version": device.ios_version,
        "status": device.status.value if hasattr(device.status, "value") else device.status,
        "battery_level": device.battery_level,
        "network_type": device.network_type,
        "wda_url": device.wda_url,
        "companion_id": device.companion_id,
        "current_apple_id": current_apple_email,
        "current_task_id": str(device.current_task_id) if device.current_task_id else None,
        "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
        "registered_at": device.registered_at.isoformat() if device.registered_at else None,
        "udid": getattr(device, "udid", None),
        "serial_number": getattr(device, "serial_number", None),
        "imei": getattr(device, "imei", None),
        "meid": getattr(device, "meid", None),
        "wifi_mac": getattr(device, "wifi_mac", None),
        "bluetooth_mac": getattr(device, "bluetooth_mac", None),
        "cpu_architecture": getattr(device, "cpu_architecture", None),
        "hardware_platform": getattr(device, "hardware_platform", None),
        "chip_id": getattr(device, "chip_id", None),
        "product_type": getattr(device, "product_type", None),
        "jailbroken": getattr(device, "jailbroken", None),
        "jailbreak_type": getattr(device, "jailbreak_type", None),
    }
