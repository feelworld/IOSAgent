import logging
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from server.src.api.auth import get_current_user
from server.src.models.task import Task, TaskSource, TaskStatus
from server.src.services import task_scheduler
from server.src.services.command_dispatcher import cancel_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tasks", tags=["tasks"])


def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


def _err(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}


def _serialize_task(task: Task) -> dict:
    return {
        "id": str(task.id),
        "task_uid": task.task_uid,
        "device_id": str(task.device_id),
        "script_id": str(task.script_id),
        "script_version": task.script_version,
        "strategy_id": str(task.strategy_id) if task.strategy_id else None,
        "status": task.status.value if hasattr(task.status, "value") else task.status,
        "params": task.params,
        "result": task.result.model_dump() if task.result else None,
        "error_message": task.error_message,
        "dispatched_at": task.dispatched_at.isoformat() if task.dispatched_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "timeout_seconds": task.timeout_seconds,
        "retry_count": task.retry_count,
        "source": task.source.value if hasattr(task.source, "value") else task.source,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


class DispatchRequest(BaseModel):
    device_ids: list[str]
    script_id: str
    script_version: int
    params: Optional[dict] = None
    timeout_seconds: int = Field(default=300, ge=10, le=7200)


@router.post("/dispatch")
async def dispatch_tasks(body: DispatchRequest, _user=Depends(get_current_user)):
    oid_device_ids = [PydanticObjectId(d) for d in body.device_ids]
    tasks = await task_scheduler.batch_dispatch(
        device_ids=oid_device_ids,
        script_id=PydanticObjectId(body.script_id),
        script_version=body.script_version,
        params=body.params,
        timeout_seconds=body.timeout_seconds,
        source=TaskSource.MANUAL,
    )
    return _ok([_serialize_task(t) for t in tasks])


@router.get("")
async def list_tasks(
    status: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort: str = Query("created_at:desc"),
    _user=Depends(get_current_user),
):
    filters = {}
    if status:
        filters["status"] = TaskStatus(status)
    if device_id:
        filters["device_id"] = PydanticObjectId(device_id)
    if source:
        filters["source"] = TaskSource(source)

    query = Task.find(filters) if filters else Task.find()
    sort_field, sort_dir = sort.split(":") if ":" in sort else (sort, "desc")
    sort_expr = f"-{sort_field}" if sort_dir == "desc" else f"+{sort_field}"

    total = await query.count()
    items = await query.sort(sort_expr).skip((page - 1) * size).limit(size).to_list()

    return _ok({
        "items": [_serialize_task(t) for t in items],
        "total": total,
        "page": page,
        "size": size,
    })


@router.get("/stats")
async def task_stats(_user=Depends(get_current_user)):
    total = await Task.count()
    pending = await Task.find(Task.status == TaskStatus.PENDING).count()
    running = await Task.find(Task.status == TaskStatus.RUNNING).count()
    success = await Task.find(Task.status == TaskStatus.SUCCESS).count()
    failed = await Task.find(Task.status == TaskStatus.FAILED).count()
    timeout = await Task.find(Task.status == TaskStatus.TIMEOUT).count()
    completed = success + failed + timeout
    return _ok({
        "total": total,
        "pending": pending,
        "running": running,
        "success": success,
        "failed": failed,
        "timeout": timeout,
        "success_rate": round(success / completed, 4) if completed > 0 else 0,
    })


@router.get("/{task_id}")
async def get_task(task_id: str, _user=Depends(get_current_user)):
    task = await Task.get(PydanticObjectId(task_id))
    if not task:
        return _err(40401, "Task not found")
    return _ok(_serialize_task(task))


@router.post("/{task_id}/cancel")
async def cancel(task_id: str, _user=Depends(get_current_user)):
    try:
        task = await cancel_task(PydanticObjectId(task_id))
    except ValueError as e:
        return _err(40001, str(e))
    return _ok(_serialize_task(task))
