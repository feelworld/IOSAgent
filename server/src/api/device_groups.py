import logging
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.src.api.auth import get_current_user
from server.src.models.device import Device
from server.src.models.device_group import DeviceGroup

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/groups", tags=["device-groups"])


def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def _err(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def _serialize_group(group: DeviceGroup) -> dict:
    return {
        "id": str(group.id),
        "name": group.name,
        "description": group.description,
        "device_ids": [str(d) for d in group.device_ids],
        "device_count": len(group.device_ids),
        "config_overrides": group.config_overrides,
        "created_at": group.created_at.isoformat() if group.created_at else None,
    }


class CreateGroupRequest(BaseModel):
    name: str
    description: Optional[str] = None


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class AddDevicesRequest(BaseModel):
    device_ids: list[str]


@router.get("")
async def list_groups(_user=Depends(get_current_user)):
    groups = await DeviceGroup.find_all().to_list()
    return _ok([_serialize_group(g) for g in groups])


@router.post("")
async def create_group(body: CreateGroupRequest, _user=Depends(get_current_user)):
    existing = await DeviceGroup.find_one(DeviceGroup.name == body.name)
    if existing:
        return _err(40901, "Group name already exists")

    group = DeviceGroup(name=body.name, description=body.description)
    await group.insert()
    return _ok(_serialize_group(group))


@router.put("/{group_id}")
async def update_group(group_id: str, body: UpdateGroupRequest, _user=Depends(get_current_user)):
    group = await DeviceGroup.get(PydanticObjectId(group_id))
    if not group:
        return _err(40401, "Group not found")

    if body.name is not None:
        dup = await DeviceGroup.find_one(
            DeviceGroup.name == body.name, DeviceGroup.id != group.id
        )
        if dup:
            return _err(40901, "Group name already exists")
        group.name = body.name

    if body.description is not None:
        group.description = body.description

    await group.save()
    return _ok(_serialize_group(group))


@router.delete("/{group_id}")
async def delete_group(group_id: str, _user=Depends(get_current_user)):
    group = await DeviceGroup.get(PydanticObjectId(group_id))
    if not group:
        return _err(40401, "Group not found")

    for device_id in group.device_ids:
        device = await Device.get(device_id)
        if device and group.id in device.group_ids:
            device.group_ids.remove(group.id)
            await device.save()

    await group.delete()
    return _ok(message="Group deleted")


@router.post("/{group_id}/devices")
async def add_devices_to_group(
    group_id: str, body: AddDevicesRequest, _user=Depends(get_current_user)
):
    group = await DeviceGroup.get(PydanticObjectId(group_id))
    if not group:
        return _err(40401, "Group not found")

    added = 0
    for did in body.device_ids:
        oid = PydanticObjectId(did)
        device = await Device.get(oid)
        if not device:
            continue
        if oid not in group.device_ids:
            group.device_ids.append(oid)
        if group.id not in device.group_ids:
            device.group_ids.append(group.id)
            await device.save()
        added += 1

    await group.save()
    return _ok({"added": added, "group": _serialize_group(group)})
