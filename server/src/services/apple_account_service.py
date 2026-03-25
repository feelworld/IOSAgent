import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId

from server.src.models.apple_account import AppleAccount, AppleAccountStatus
from server.src.models.device import Device
from server.src.utils.crypto import decrypt_aes256
from server.src.ws.admin_handler import broadcast_to_admins

logger = logging.getLogger(__name__)

DEFAULT_MAX_ACCOUNTS_PER_DEVICE = 3


async def get_max_accounts_per_device() -> int:
    """Read global config for max accounts per device, fallback to default."""
    try:
        from server.src.models.configuration import Configuration
        cfg = await Configuration.find_one(Configuration.key == "max_accounts_per_device")
        if cfg:
            return int(cfg.value)
    except Exception:
        pass
    return DEFAULT_MAX_ACCOUNTS_PER_DEVICE


async def auto_assign_accounts(device_id: PydanticObjectId) -> list[AppleAccount]:
    """Assign accounts from the pool to a device until it reaches the limit."""
    max_per_device = await get_max_accounts_per_device()

    current = await AppleAccount.find(
        AppleAccount.bound_device_id == device_id,
        AppleAccount.status == AppleAccountStatus.ACTIVE,
    ).to_list()

    need = max_per_device - len(current)
    if need <= 0:
        return current

    available = await AppleAccount.find(
        AppleAccount.bound_device_id == None,
        AppleAccount.status == AppleAccountStatus.ACTIVE,
    ).sort("+created_at").limit(need).to_list()

    for acc in available:
        acc.bound_device_id = device_id
        if not current:
            acc.is_primary = True
        await acc.save()
        current.append(acc)

    logger.info("auto_assign: device %s now has %d account(s) (assigned %d new)",
                device_id, len(current), len(available))
    return current


async def get_next_account(device_id: PydanticObjectId) -> AppleAccount | None:
    """Get the next usable account for a device. Auto-assigns from pool if needed."""
    accounts = await AppleAccount.find(
        AppleAccount.bound_device_id == device_id,
        AppleAccount.status == AppleAccountStatus.ACTIVE,
    ).sort("+last_used_at").to_list()

    if not accounts:
        assigned = await auto_assign_accounts(device_id)
        accounts = [a for a in assigned if a.status == AppleAccountStatus.ACTIVE]

    if not accounts:
        logger.warning("get_next_account: no accounts available for device %s", device_id)
        return None

    chosen = accounts[0]
    chosen.last_used_at = datetime.now(timezone.utc)
    await chosen.save()
    return chosen


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
