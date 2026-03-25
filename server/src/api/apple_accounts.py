import logging
from datetime import datetime, timezone
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


async def _serialize_account(acc: AppleAccount) -> dict:
    bound_device_name = None
    bound_device_uid = None
    if acc.bound_device_id:
        device = await Device.get(acc.bound_device_id)
        if device:
            bound_device_name = device.name or device.device_uid
            bound_device_uid = device.device_uid

    return {
        "id": str(acc.id),
        "email": acc.email,
        "status": acc.status.value if hasattr(acc.status, "value") else acc.status,
        "bound_device_id": str(acc.bound_device_id) if acc.bound_device_id else None,
        "bound_device_name": bound_device_name,
        "bound_device_uid": bound_device_uid,
        "is_primary": acc.is_primary,
        "pool_group": acc.pool_group,
        "last_used_at": acc.last_used_at.isoformat() if acc.last_used_at else None,
        "banned_at": acc.banned_at.isoformat() if acc.banned_at else None,
        "created_at": acc.created_at.isoformat() if acc.created_at else None,
    }


class CreateAccountRequest(BaseModel):
    email: str
    password: str
    pool_group: str = "default"


class BatchImportRequest(BaseModel):
    accounts_text: str
    pool_group: str = "default"


class BindRequest(BaseModel):
    device_id: str
    is_primary: bool = False


# ── Stats ──────────────────────────────────────────────────────

@router.get("/stats")
async def account_stats(_user=Depends(get_current_user)):
    total = await AppleAccount.find().count()
    active = await AppleAccount.find(AppleAccount.status == AppleAccountStatus.ACTIVE).count()
    banned = await AppleAccount.find(AppleAccount.status == AppleAccountStatus.BANNED).count()
    suspended = await AppleAccount.find(AppleAccount.status == AppleAccountStatus.SUSPENDED).count()
    assigned = await AppleAccount.find(AppleAccount.bound_device_id != None).count()
    unassigned = await AppleAccount.find(
        AppleAccount.bound_device_id == None,
        AppleAccount.status == AppleAccountStatus.ACTIVE,
    ).count()
    return _ok({
        "total": total,
        "active": active,
        "banned": banned,
        "suspended": suspended,
        "assigned": assigned,
        "unassigned": unassigned,
    })


# ── List ───────────────────────────────────────────────────────

@router.get("")
async def list_accounts(
    status: Optional[str] = Query(None),
    pool_group: Optional[str] = Query(None),
    bound: Optional[str] = Query(None),
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

    if bound == "yes":
        query = query.find(AppleAccount.bound_device_id != None)
    elif bound == "no":
        query = query.find(AppleAccount.bound_device_id == None)

    total = await query.count()
    items = await query.sort("-created_at").skip((page - 1) * size).limit(size).to_list()

    return _ok({
        "items": [await _serialize_account(a) for a in items],
        "total": total,
        "page": page,
        "size": size,
    })


# ── Create single ─────────────────────────────────────────────

@router.post("")
async def create_account(body: CreateAccountRequest, _user=Depends(get_current_user)):
    existing = await AppleAccount.find_one(AppleAccount.email == body.email)
    if existing:
        return _err(40901, "Apple account email already exists")

    account = AppleAccount(
        email=body.email,
        encrypted_password=encrypt_aes256(body.password),
        status=AppleAccountStatus.ACTIVE,
        pool_group=body.pool_group,
    )
    await account.insert()
    return _ok(await _serialize_account(account))


# ── Batch import ───────────────────────────────────────────────

@router.post("/batch-import")
async def batch_import(body: BatchImportRequest, _user=Depends(get_current_user)):
    """Import accounts in bulk. Each line: email----password"""
    lines = [l.strip() for l in body.accounts_text.strip().splitlines() if l.strip()]
    imported, skipped, errors = 0, 0, []

    for i, line in enumerate(lines, 1):
        sep = "----" if "----" in line else (":" if ":" in line else None)
        if not sep:
            errors.append(f"Line {i}: invalid format (use email----password)")
            continue

        parts = line.split(sep, 1)
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            errors.append(f"Line {i}: invalid format")
            continue

        email = parts[0].strip()
        password = parts[1].strip()

        existing = await AppleAccount.find_one(AppleAccount.email == email)
        if existing:
            skipped += 1
            continue

        account = AppleAccount(
            email=email,
            encrypted_password=encrypt_aes256(password),
            status=AppleAccountStatus.ACTIVE,
            pool_group=body.pool_group,
        )
        await account.insert()
        imported += 1

    return _ok({
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "total_lines": len(lines),
    })


# ── Bind / Unbind ─────────────────────────────────────────────

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

    return _ok(await _serialize_account(account))


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
    return _ok(await _serialize_account(account))


# ── Device-scoped account management ──────────────────────────

@router.get("/by-device/{device_id}")
async def list_device_accounts(device_id: str, _user=Depends(get_current_user)):
    """List all accounts bound to a specific device."""
    oid = PydanticObjectId(device_id)
    accounts = await AppleAccount.find(
        AppleAccount.bound_device_id == oid,
    ).sort("-is_primary").to_list()
    return _ok([await _serialize_account(a) for a in accounts])


@router.post("/{account_id}/unbind-and-refill")
async def unbind_and_refill(account_id: str, _user=Depends(get_current_user)):
    """Unbind account from device, then auto-replenish from pool if possible."""
    account = await AppleAccount.get(PydanticObjectId(account_id))
    if not account:
        return _err(40401, "Apple account not found")

    device_id = account.bound_device_id
    if not device_id:
        return _ok(await _serialize_account(account))

    if account.is_primary:
        device = await Device.get(device_id)
        if device and device.current_apple_id == account.id:
            device.current_apple_id = None
            await device.save()

    account.bound_device_id = None
    account.is_primary = False
    await account.save()

    from server.src.services.apple_account_service import auto_assign_accounts
    new_accounts = await auto_assign_accounts(device_id)

    if new_accounts and device_id:
        device = await Device.get(device_id)
        if device and not device.current_apple_id:
            primary = next((a for a in new_accounts if a.is_primary), None)
            if primary:
                device.current_apple_id = primary.id
                await device.save()

    return _ok({
        "removed": await _serialize_account(account),
        "device_accounts": [await _serialize_account(a) for a in new_accounts],
    })


# ── Distribute to all online devices ─────────────────────────

@router.post("/distribute-all")
async def distribute_to_all_devices(_user=Depends(get_current_user)):
    """Auto-assign accounts from pool to all online devices that need them."""
    from server.src.services.apple_account_service import auto_assign_accounts

    online_devices = await Device.find(Device.status == "online").to_list()
    results = []
    for device in online_devices:
        accounts = await auto_assign_accounts(device.id)
        if accounts and not device.current_apple_id:
            primary = next((a for a in accounts if a.is_primary), None)
            if primary:
                device.current_apple_id = primary.id
                await device.save()
        results.append({
            "device_uid": device.device_uid,
            "device_name": device.name,
            "account_count": len(accounts),
        })
    return _ok({"devices": results, "total_devices": len(results)})


# ── Enable / Disable ──────────────────────────────────────────

@router.post("/{account_id}/disable")
async def disable_account(account_id: str, _user=Depends(get_current_user)):
    account = await AppleAccount.get(PydanticObjectId(account_id))
    if not account:
        return _err(40401, "Apple account not found")

    account.status = AppleAccountStatus.SUSPENDED
    await account.save()
    return _ok(await _serialize_account(account))


@router.post("/{account_id}/enable")
async def enable_account(account_id: str, _user=Depends(get_current_user)):
    account = await AppleAccount.get(PydanticObjectId(account_id))
    if not account:
        return _err(40401, "Apple account not found")

    account.status = AppleAccountStatus.ACTIVE
    account.banned_at = None
    await account.save()
    return _ok(await _serialize_account(account))
