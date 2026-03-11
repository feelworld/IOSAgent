import logging
from datetime import datetime, timezone
from typing import Any, Optional

from beanie import PydanticObjectId

from server.src.models.configuration import ConfigScope, Configuration

logger = logging.getLogger(__name__)


async def push_config_to_clients(
    scope: ConfigScope,
    scope_id: Optional[PydanticObjectId],
    configs: dict[str, Any],
) -> int:
    """Push config update to companion machines via WebSocket.
    Returns the number of clients notified."""
    import uuid
    from server.src.ws.client_handler import send_to_client, client_connections

    message_base = {
        "type": "config.update",
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    notified = 0

    if scope == ConfigScope.DEVICE:
        from server.src.models.device import Device
        device = await Device.get(scope_id)
        if device and device.companion_id:
            msg = {**message_base, "payload": {
                "scope": "device", "device_uid": device.device_uid, "configs": configs,
            }}
            if await send_to_client(device.companion_id, msg):
                notified += 1

    elif scope == ConfigScope.DEVICE_GROUP:
        from server.src.models.device_group import DeviceGroup
        from server.src.models.device import Device
        group = await DeviceGroup.get(scope_id)
        if group:
            devices = await Device.find({"_id": {"$in": group.device_ids}}).to_list()
            companion_ids = {d.companion_id for d in devices if d.companion_id}
            for cid in companion_ids:
                msg = {**message_base, "payload": {
                    "scope": "device_group", "configs": configs,
                }}
                if await send_to_client(cid, msg):
                    notified += 1

    elif scope == ConfigScope.GLOBAL:
        for cid in list(client_connections.keys()):
            msg = {**message_base, "payload": {
                "scope": "global", "configs": configs,
            }}
            if await send_to_client(cid, msg):
                notified += 1

    logger.info("Config pushed to %d client(s), scope=%s", notified, scope.value)
    return notified


async def get_config(
    key: str,
    device_id: Optional[PydanticObjectId] = None,
    group_ids: Optional[list[PydanticObjectId]] = None,
) -> Any:
    if device_id:
        doc = await Configuration.find_one(
            Configuration.key == key,
            Configuration.scope == ConfigScope.DEVICE,
            Configuration.scope_id == device_id,
        )
        if doc:
            return doc.value

    if group_ids:
        doc = await Configuration.find_one(
            Configuration.key == key,
            Configuration.scope == ConfigScope.DEVICE_GROUP,
            {"scope_id": {"$in": group_ids}},
        )
        if doc:
            return doc.value

    doc = await Configuration.find_one(
        Configuration.key == key,
        Configuration.scope == ConfigScope.GLOBAL,
    )
    return doc.value if doc else None


async def set_config(
    key: str,
    value: Any,
    scope: str | ConfigScope,
    scope_id: Optional[PydanticObjectId] = None,
    updated_by: Optional[PydanticObjectId] = None,
) -> Configuration:
    if isinstance(scope, str):
        scope = ConfigScope(scope)

    existing = await Configuration.find_one(
        Configuration.key == key,
        Configuration.scope == scope,
        Configuration.scope_id == scope_id,
    )

    if existing:
        existing.value = value
        existing.updated_by = updated_by
        existing.updated_at = datetime.now(timezone.utc)
        await existing.save()
        return existing

    doc = Configuration(
        key=key,
        value=value,
        scope=scope,
        scope_id=scope_id,
        updated_by=updated_by,
        updated_at=datetime.now(timezone.utc),
    )
    await doc.insert()
    return doc
