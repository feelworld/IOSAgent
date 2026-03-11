import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId

from server.src.models.apple_account import AppleAccount, AppleAccountStatus
from server.src.models.device import Device
from server.src.utils.crypto import decrypt_aes256
from server.src.ws.admin_handler import broadcast_to_admins

logger = logging.getLogger(__name__)


async def auto_switch_account(device_id: PydanticObjectId, reason: str) -> AppleAccount | None:
    """When an Apple ID is banned, find a backup from the same pool and switch."""
    device = await Device.get(device_id)
    if not device:
        logger.warning(f"auto_switch: device {device_id} not found")
        return None

    current_account = (
        await AppleAccount.find_one(
            AppleAccount.bound_device_id == device.id,
            AppleAccount.is_primary == True,
        )
        if device.current_apple_id is None
        else await AppleAccount.get(device.current_apple_id)
    )

    pool_group = current_account.pool_group if current_account else None
    if not pool_group:
        logger.warning(f"auto_switch: no pool_group for device {device_id}")
        return None

    if current_account:
        current_account.status = AppleAccountStatus.BANNED
        current_account.banned_at = datetime.now(timezone.utc)
        current_account.is_primary = False
        await current_account.save()

    backup = await AppleAccount.find_one(
        AppleAccount.pool_group == pool_group,
        AppleAccount.status == AppleAccountStatus.ACTIVE,
        AppleAccount.bound_device_id == None,
    )
    if not backup:
        logger.warning(f"auto_switch: no backup account in pool '{pool_group}'")
        await broadcast_to_admins({
            "type": "alert",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "level": "warning",
                "message": f"No backup Apple account in pool '{pool_group}' for device {device.device_uid}",
            },
        })
        return None

    backup.bound_device_id = device.id
    backup.is_primary = True
    backup.last_used_at = datetime.now(timezone.utc)
    await backup.save()

    device.current_apple_id = backup.id
    await device.save()

    from server.src.ws.client_handler import send_to_client

    password = decrypt_aes256(backup.encrypted_password)
    await send_to_client(device.companion_id, {
        "type": "apple_account.switch",
        "payload": {
            "device_uid": device.device_uid,
            "email": backup.email,
            "password": password,
            "reason": reason,
        },
    })

    await broadcast_to_admins({
        "type": "alert",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "level": "info",
            "message": f"Apple account switched on {device.device_uid}: {current_account.email if current_account else '?'} -> {backup.email}",
        },
    })

    logger.info(f"auto_switch: device {device.device_uid} switched to {backup.email}")
    return backup
