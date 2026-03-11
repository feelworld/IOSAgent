import logging
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from server.src.api.auth import get_current_user
from server.src.models.apple_account import AppleAccount, AppleAccountStatus
from server.src.models.device import Device
from server.src.utils.crypto import encrypt_aes256

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/apple-accounts", tags=["apple-accounts"])


def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def _err(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def _serialize_account(acc: AppleAccount) -> dict:
    return {
        "id": str(acc.id),
        "email": acc.email,
        "status": acc.status.value if hasattr(acc.status, "value") else acc.status,
        "bound_device_id": str(acc.bound_device_id) if acc.bound_device_id else None,
        "is_primary": acc.is_primary,
        "pool_group": acc.pool_group,
        "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
        "banned_at": acc.banned_at.isoformat() if acc.banned_at else None,
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
    }


class CreateAccountRequest(BaseModel):
    email: str
    password: str
    pool_group: str


class BindRequest(BaseModel):
    device_id: str
    is_primary: bool = False


@router.get("")
async def list_accounts(
    status: Optional[str] = Query(None),
    pool_group: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    filters = {}
    if status:
        filters["status"] = AppleAccountStatus(status)
    if pool_group:
        filters["pool_group"] = pool_group

    query = AppleAccount.find(filters) if filters else AppleAccount.find()
    total = await query.count()
    items = await query.sort("-created_at").skip((page - 1) * size).limit(size).to_list()

    return _ok({
        "items": [_serialize_account(a) for a in items],
        "total": total,
        "page": page,
        "size": size,
    })


@router.post("")
async def create_account(body: CreateAccountRequest, _user=Depends(get_current_user)):
    existing = await AppleAccount.find_one(AppleAccount.email == body.email)
    if existing:
        return _err(40901, "Apple account email already exists")

    account = AppleAccount(
        email=body.email,
        encrypted_password=encrypt_aes256(body.password),
        pool_group=body.pool_group,
    )
    await account.insert()
    return _ok(_serialize_account(account))


@router.post("/{account_id}/bind")
async def bind_to_device(
    account_id: str, body: BindRequest, _user=Depends(get_current_user)
):
    account = await AppleAccount.get(PydanticObjectId(account_id))
    if not account:
        return _err(40401, "Apple account not found")

    device = await Device.get(PydanticObjectId(body.device_id))
    if not device:
        return _err(40402, "Device not found")

    if body.is_primary:
        prev = await AppleAccount.find_one(
            AppleAccount.bound_device_id == device.id,
            AppleAccount.is_primary == True,
        )
        if prev and prev.id != account.id:
            prev.is_primary = False
            await prev.save()

    account.bound_device_id = device.id
    account.is_primary = body.is_primary
    await account.save()

    if body.is_primary:
        device.current_apple_id = account.id
        await device.save()

    return _ok(_serialize_account(account))


@router.post("/{account_id}/unbind")
async def unbind_from_device(account_id: str, _user=Depends(get_current_user)):
    account = await AppleAccount.get(PydanticObjectId(account_id))
    if not account:
        return _err(40401, "Apple account not found")

    if account.bound_device_id and account.is_primary:
        device = await Device.get(account.bound_device_id)
        if device and device.current_apple_id == account.id:
            device.current_apple_id = None
            await device.save()

    account.bound_device_id = None
    account.is_primary = False
    await account.save()
    return _ok(_serialize_account(account))
