import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from beanie import PydanticObjectId

from server.src.models.device import Device, DeviceStatus
from server.src.models.script import ScriptVersion
from server.src.models.task import Task, TaskSource, TaskStatus
from server.src.ws.admin_handler import broadcast_to_admins

logger = logging.getLogger(__name__)

CANCELLABLE_STATUSES = {TaskStatus.PENDING, TaskStatus.DISPATCHED, TaskStatus.RUNNING}


async def dispatch_command(
    device_id: PydanticObjectId,
    script_id: PydanticObjectId,
    script_version: int,
    params: Optional[dict] = None,
    timeout_seconds: int = 300,
    source: TaskSource = TaskSource.MANUAL,
    strategy_id: Optional[PydanticObjectId] = None,
) -> Task:
    """Create a task, dispatch it to the companion machine via WS."""
    device = await Device.get(device_id)
    if not device:
        raise ValueError(f"Device {device_id} not found")

    script_ver = await ScriptVersion.find_one(
        ScriptVersion.script_id == script_id,
        ScriptVersion.version == script_version,
    )
    if not script_ver:
        raise ValueError(
            f"ScriptVersion not found: script_id={script_id}, version={script_version}"
        )

    task = Task(
        task_uid=str(uuid4()),
        device_id=device_id,
        script_id=script_id,
        script_version=script_version,
        strategy_id=strategy_id,
        params=params,
        timeout_seconds=timeout_seconds,
        source=source,
    )
    await task.insert()

    from server.src.ws.client_handler import send_to_client

    if device.status == DeviceStatus.OFFLINE:
        task.status = TaskStatus.FAILED
        task.error_message = "Device is offline"
        task.completed_at = datetime.now(timezone.utc)
        await task.save()
        return task

    companion_id = device.companion_id

    script_payload: dict = {
        "script_type": getattr(script_ver, "script_type", "steps"),
        "steps": [s.model_dump() for s in script_ver.steps],
    }
    python_code = getattr(script_ver, "python_code", None)
    if python_code:
        script_payload["python_code"] = python_code

    message = {
        "type": "command.dispatch",
        "payload": {
            "task_uid": task.task_uid,
            "task_id": str(task.id),
            "device_uid": device.device_uid,
            "script_id": str(script_id),
            "script_version": script_version,
            "script": script_payload,
            "params": params or {},
            "timeout_seconds": timeout_seconds,
        },
    }

    sent = await send_to_client(companion_id, message)
    if not sent:
        task.status = TaskStatus.FAILED
        task.error_message = "Companion machine not connected"
        task.completed_at = datetime.now(timezone.utc)
        await task.save()
        return task

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.DISPATCHED
    task.dispatched_at = now
    await task.save()

    device.status = DeviceStatus.BUSY
    device.current_task_id = task.id
    await device.save()

    await broadcast_to_admins({
        "type": "task.updated",
        "timestamp": now.isoformat(),
        "payload": {"task_id": str(task.id), "task_uid": task.task_uid, "status": task.status.value},
    })

    return task


async def cancel_task(task_id: PydanticObjectId) -> Task:
    """Cancel a running/pending/dispatched task."""
    task = await Task.get(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    if task.status not in CANCELLABLE_STATUSES:
        raise ValueError(f"Task in status '{task.status.value}' cannot be cancelled")

    device = await Device.get(task.device_id)
    if device:
        from server.src.ws.client_handler import send_to_client

        await send_to_client(device.companion_id, {
            "type": "command.cancel",
            "payload": {"task_uid": task.task_uid, "task_id": str(task.id)},
        })

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.CANCELLED
    task.completed_at = now
    await task.save()

    if device and device.current_task_id == task.id:
        device.status = DeviceStatus.ONLINE
        device.current_task_id = None
        await device.save()

    await broadcast_to_admins({
        "type": "task.updated",
        "timestamp": now.isoformat(),
        "payload": {"task_id": str(task.id), "task_uid": task.task_uid, "status": task.status.value},
    })

    return task
