from typing import Any, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from server.src.api.auth import get_current_user
from server.src.models.configuration import ConfigScope
from server.src.services import config_service

router = APIRouter(prefix="/configs", tags=["configs"])


def _ok(data: dict | list | None = None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


class ConfigUpsertRequest(BaseModel):
    key: str
    value: Any
    scope: ConfigScope
    scope_id: Optional[str] = None


def _config_to_dict(cfg) -> dict:
    return {
        "id": str(cfg.id),
        "key": cfg.key,
        "value": cfg.value,
        "scope": cfg.scope.value,
        "scope_id": str(cfg.scope_id) if cfg.scope_id else None,
        "description": cfg.description,
        "updated_by": str(cfg.updated_by) if cfg.updated_by else None,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


@router.get("")
async def list_configs(
    scope: Optional[ConfigScope] = Query(None),
    scope_id: Optional[str] = Query(None),
    _user=Depends(get_current_user),
):
    from server.src.models.configuration import Configuration

    query = {}
    if scope is not None:
        query["scope"] = scope
    if scope_id is not None:
        query["scope_id"] = PydanticObjectId(scope_id)

    docs = await Configuration.find(query).to_list()
    return _ok([_config_to_dict(d) for d in docs])


@router.put("")
async def upsert_config(
    body: ConfigUpsertRequest,
    user=Depends(get_current_user),
):
    scope_id = PydanticObjectId(body.scope_id) if body.scope_id else None
    cfg = await config_service.set_config(
        key=body.key,
        value=body.value,
        scope=body.scope,
        scope_id=scope_id,
        updated_by=user.id,
    )
    return _ok(_config_to_dict(cfg))
