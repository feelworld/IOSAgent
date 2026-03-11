from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends

from server.src.api.auth import get_current_user
from server.src.models.device import Device, DeviceStatus
from server.src.models.strategy import Strategy, StrategyPhase, StrategyStatus
from server.src.models.task import Task, TaskStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _ok(data=None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


@router.get("")
async def dashboard(_user=Depends(get_current_user)):
    total_devices = await Device.count()
    online = await Device.find(Device.status == DeviceStatus.ONLINE).count()
    offline = await Device.find(Device.status == DeviceStatus.OFFLINE).count()
    busy = await Device.find(Device.status == DeviceStatus.BUSY).count()
    error = await Device.find(Device.status == DeviceStatus.ERROR).count()

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    today_tasks = Task.find(Task.created_at >= today_start)
    tasks_total = await today_tasks.count()
    tasks_success = await Task.find(
        Task.created_at >= today_start,
        Task.status == TaskStatus.SUCCESS,
    ).count()
    tasks_failed = await Task.find(
        Task.created_at >= today_start,
        Task.status == TaskStatus.FAILED,
    ).count()
    tasks_running = await Task.find(
        Task.created_at >= today_start,
        Task.status == TaskStatus.RUNNING,
    ).count()

    active_explore = await Strategy.find(
        Strategy.phase == StrategyPhase.EXPLORE,
        Strategy.status == StrategyStatus.ACTIVE,
    ).count()
    active_execute = await Strategy.find(
        Strategy.phase == StrategyPhase.EXECUTE,
        Strategy.status == StrategyStatus.ACTIVE,
    ).count()

    today_success_tasks = await Task.find(
        Task.created_at >= today_start,
        Task.status == TaskStatus.SUCCESS,
    ).to_list()
    downloads_today = sum(
        t.result.download_count for t in today_success_tasks if t.result
    )

    all_success_tasks = await Task.find(
        Task.status == TaskStatus.SUCCESS,
    ).to_list()
    downloads_total = sum(
        t.result.download_count for t in all_success_tasks if t.result
    )

    return _ok({
        "devices": {
            "total": total_devices,
            "online": online,
            "offline": offline,
            "busy": busy,
            "error": error,
        },
        "tasks_today": {
            "total": tasks_total,
            "success": tasks_success,
            "failed": tasks_failed,
            "running": tasks_running,
        },
        "strategies": {
            "active_explore": active_explore,
            "active_execute": active_execute,
        },
        "downloads_today": downloads_today,
        "downloads_total": downloads_total,
    })
