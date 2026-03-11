import logging
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from server.src.api.auth import get_current_user
from server.src.models.script import Script, ScriptStatus, ScriptType, ScriptVersion
from server.src.services import script_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scripts", tags=["scripts"])


def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def _err(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def _serialize_script(s: Script) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "script_type": s.script_type.value if hasattr(s.script_type, "value") else s.script_type,
        "current_version": s.current_version,
        "status": s.status.value if hasattr(s.status, "value") else s.status,
        "created_by": str(s.created_by) if s.created_by else None,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def _serialize_version(v: ScriptVersion) -> dict:
    result = {
        "id": str(v.id),
        "script_id": str(v.script_id),
        "version": v.version,
        "script_type": v.script_type.value if hasattr(v.script_type, "value") else v.script_type,
        "steps": [step.model_dump() for step in v.steps],
        "changelog": v.changelog,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "created_at": v.created_at.isoformat(),
    }
    if v.python_code:
        result["python_code"] = v.python_code
    return result


class CreateScriptRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    script_type: str = "steps"
    steps: list[dict] = Field(default_factory=list)
    python_code: Optional[str] = None


class UpdateScriptRequest(BaseModel):
    steps: list[dict] = Field(..., min_length=1)
    changelog: Optional[str] = None


class RollbackRequest(BaseModel):
    target_version: int = Field(..., ge=1)


class GrayReleaseRequest(BaseModel):
    device_ids: list[str] = Field(..., min_length=1)


@router.get("")
async def list_scripts(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    filters = {}
    if status:
        filters["status"] = ScriptStatus(status)

    query = Script.find(filters) if filters else Script.find()
    total = await query.count()
    items = await query.sort("-created_at").skip((page - 1) * size).limit(size).to_list()

    return _ok({
        "items": [_serialize_script(s) for s in items],
        "total": total,
        "page": page,
        "size": size,
    })


@router.post("")
async def create_script(body: CreateScriptRequest, user=Depends(get_current_user)):
    try:
        script = await script_manager.create_script(
            name=body.name,
            description=body.description,
            script_type=body.script_type,
            steps=body.steps,
            python_code=body.python_code,
            created_by=user.id,
        )
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(_serialize_script(script))


@router.put("/{script_id}")
async def update_script(
    script_id: str,
    body: UpdateScriptRequest,
    user=Depends(get_current_user),
):
    try:
        version = await script_manager.update_script(
            script_id=PydanticObjectId(script_id),
            steps=body.steps,
            changelog=body.changelog,
            updated_by=user.id,
        )
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(_serialize_version(version))


@router.post("/{script_id}/publish")
async def publish_script(script_id: str, _user=Depends(get_current_user)):
    try:
        script = await script_manager.publish_script(PydanticObjectId(script_id))
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(_serialize_script(script))


@router.post("/{script_id}/rollback")
async def rollback_script(
    script_id: str,
    body: RollbackRequest,
    _user=Depends(get_current_user),
):
    try:
        script = await script_manager.rollback_script(
            script_id=PydanticObjectId(script_id),
            target_version=body.target_version,
        )
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(_serialize_script(script))


@router.get("/{script_id}/versions")
async def get_versions(script_id: str, _user=Depends(get_current_user)):
    versions = await script_manager.get_versions(PydanticObjectId(script_id))
    return _ok([_serialize_version(v) for v in versions])


@router.post("/{script_id}/gray-release")
async def gray_release(
    script_id: str,
    body: GrayReleaseRequest,
    _user=Depends(get_current_user),
):
    try:
        device_oids = [PydanticObjectId(d) for d in body.device_ids]
        tasks = await script_manager.gray_release(
            script_id=PydanticObjectId(script_id),
            device_ids=device_oids,
        )
    except ValueError as e:
        return _err(40001, str(e))

    from server.src.api.tasks import _serialize_task
    return _ok([_serialize_task(t) for t in tasks])
