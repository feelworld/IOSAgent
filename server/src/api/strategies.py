import logging
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from server.src.api.auth import get_current_user
from server.src.models.strategy import Strategy, StrategyPhase, StrategyStatus
from server.src.services import strategy_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategies", tags=["strategies"])


def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def _err(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def _serialize_strategy(s: Strategy) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "script_id": str(s.script_id),
        "script_version": s.script_version,
        "params": s.params,
        "phase": s.phase.value,
        "status": s.status.value,
        "effectiveness_score": s.effectiveness_score,
        "total_executions": s.total_executions,
        "successful_executions": s.successful_executions,
        "total_downloads": s.total_downloads,
        "explore_session_id": s.explore_session_id,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Explore
# ---------------------------------------------------------------------------

class ExploreStartRequest(BaseModel):
    script_id: str
    device_count: int = Field(ge=1, le=100)
    rounds: int = Field(ge=1, le=50)
    param_variations: list[dict]


@router.post("/explore/start")
async def explore_start(body: ExploreStartRequest, _user=Depends(get_current_user)):
    try:
        result = await strategy_engine.start_explore(
            script_id=body.script_id,
            device_count=body.device_count,
            rounds=body.rounds,
            param_variations=body.param_variations,
        )
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(result)


@router.post("/explore/{session_id}/stop")
async def explore_stop(session_id: str, _user=Depends(get_current_user)):
    await strategy_engine.stop_explore(session_id)
    return _ok(message="Explore session stopped")


@router.get("/explore/{session_id}/analysis")
async def explore_analysis(session_id: str, _user=Depends(get_current_user)):
    result = await strategy_engine.get_explore_analysis(session_id)
    return _ok(result)


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

class ExecuteStartRequest(BaseModel):
    strategy_ids: list[str]
    device_ids: list[str] = Field(default_factory=list)


@router.post("/execute/start")
async def execute_start(body: ExecuteStartRequest, _user=Depends(get_current_user)):
    try:
        result = await strategy_engine.start_execute(
            strategy_ids=body.strategy_ids,
            device_ids=body.device_ids or None,
        )
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(result)


# ---------------------------------------------------------------------------
# List & Monitor
# ---------------------------------------------------------------------------

@router.get("")
async def list_strategies(
    phase: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _user=Depends(get_current_user),
):
    filters: dict = {}
    if phase:
        filters["phase"] = StrategyPhase(phase)
    if status:
        filters["status"] = StrategyStatus(status)

    query = Strategy.find(filters) if filters else Strategy.find()
    total = await query.count()
    items = await query.sort("-created_at").skip((page - 1) * size).limit(size).to_list()

    return _ok({
        "items": [_serialize_strategy(s) for s in items],
        "total": total,
        "page": page,
        "size": size,
    })


@router.get("/{strategy_id}/monitor")
async def strategy_monitor(strategy_id: str, _user=Depends(get_current_user)):
    try:
        result = await strategy_engine.get_effectiveness_monitor(strategy_id)
    except ValueError as e:
        return _err(40401, str(e))
    return _ok(result)
