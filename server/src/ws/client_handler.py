import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect, Query

from server.src.services.auth_service import decode_token
from server.src.services import device_manager
from server.src.ws.admin_handler import broadcast_to_admins

logger = logging.getLogger(__name__)

client_connections: dict[str, WebSocket] = {}


async def client_ws_endpoint(
    websocket: WebSocket, machine_id: str, token: str = Query(...)
):
    """WebSocket endpoint for companion machine agents."""
    try:
        decode_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await websocket.accept()
    client_connections[machine_id] = websocket
    logger.info(f"Client connected: {machine_id}")

    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")
            msg_payload = message.get("payload", {})

            if msg_type == "device.register":
                await _handle_device_register(machine_id, msg_payload)
            elif msg_type == "heartbeat":
                await _handle_heartbeat(machine_id, msg_payload)
            elif msg_type == "task.status":
                await _handle_task_status(msg_payload)
            elif msg_type == "task.result":
                await _handle_task_result(msg_payload)
            elif msg_type == "task.error":
                await _handle_task_error(msg_payload)
            else:
                logger.warning(
                    f"Unknown message type from {machine_id}: {msg_type}"
                )
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {machine_id}")
    except Exception as e:
        logger.error(f"Client WS error ({machine_id}): {e}")
    finally:
        client_connections.pop(machine_id, None)


async def _handle_device_register(machine_id: str, payload: dict):
    """Handle device.register: register companion and its devices."""
    devices_data = payload.get("devices", [])
    registered_device_ids = []

    passthrough_keys = (
        "udid", "serial_number", "imei", "meid", "wifi_mac", "bluetooth_mac",
        "cpu_architecture", "hardware_platform", "chip_id", "product_type",
        "jailbroken", "jailbreak_type",
    )
    for dev in devices_data:
        extra = {k: dev[k] for k in passthrough_keys if k in dev}
        device = await device_manager.register_device(
            device_uid=dev["device_uid"],
            model=dev.get("model", "Unknown"),
            ios_version=dev.get("ios_version", "Unknown"),
            wda_url=dev.get("wda_url", ""),
            companion_id=machine_id,
            name=dev.get("name"),
            battery_level=dev.get("battery_level"),
            **extra,
        )
        registered_device_ids.append(device.id)

    await device_manager.register_companion(machine_id, registered_device_ids)
    logger.info(f"Registered {len(devices_data)} devices from {machine_id}")

    for dev in devices_data:
        await broadcast_to_admins(
            {
                "type": "device.status_changed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "device_uid": dev["device_uid"],
                    "old_status": "offline",
                    "new_status": "online",
                },
            }
        )


async def _handle_heartbeat(machine_id: str, payload: dict):
    """Handle heartbeat: update device statuses."""
    devices = payload.get("devices", [])
    for dev in devices:
        await device_manager.update_heartbeat(
            device_uid=dev["device_uid"],
            status=dev.get("status", "online"),
            battery_level=dev.get("battery_level"),
            network_type=dev.get("network_type"),
            current_task_id=dev.get("current_task_id"),
        )

    await broadcast_to_admins(
        {
            "type": "device.heartbeat",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"devices": devices},
        }
    )


async def _handle_task_status(payload: dict):
    """Update task status when companion reports state change (e.g. running)."""
    from server.src.models.task import Task, TaskStatus

    task_uid = payload.get("task_uid")
    new_status = payload.get("status")
    if not task_uid or not new_status:
        return

    task = await Task.find_one(Task.task_uid == task_uid)
    if not task:
        logger.warning(f"task.status for unknown task_uid: {task_uid}")
        return

    try:
        task.status = TaskStatus(new_status)
    except ValueError:
        logger.warning(f"Invalid task status value: {new_status}")
        return

    now = datetime.now(timezone.utc)
    if task.status == TaskStatus.RUNNING and not task.started_at:
        task.started_at = now
    await task.save()

    await broadcast_to_admins({
        "type": "task.updated",
        "timestamp": now.isoformat(),
        "payload": {"task_id": str(task.id), "task_uid": task.task_uid, "status": task.status.value},
    })


async def _handle_task_result(payload: dict):
    """Handle successful task completion from companion."""
    from server.src.models.task import Task, TaskResult, TaskStatus
    from server.src.models.device import Device, DeviceStatus

    task_uid = payload.get("task_uid")
    if not task_uid:
        return

    task = await Task.find_one(Task.task_uid == task_uid)
    if not task:
        logger.warning(f"task.result for unknown task_uid: {task_uid}")
        return

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.SUCCESS
    task.completed_at = now
    result_data = payload.get("result", {})
    task.result = TaskResult(
        stdout=result_data.get("stdout"),
        stderr=result_data.get("stderr"),
        screenshots=result_data.get("screenshots", []),
        download_count=result_data.get("download_count", 0),
        duration_seconds=result_data.get("duration_seconds"),
    )
    await task.save()

    device = await Device.get(task.device_id)
    if device:
        device.status = DeviceStatus.ONLINE
        device.current_task_id = None
        await device.save()

    await broadcast_to_admins({
        "type": "task.completed",
        "timestamp": now.isoformat(),
        "payload": {
            "task_id": str(task.id),
            "task_uid": task.task_uid,
            "status": "success",
            "device_id": str(task.device_id),
        },
    })


async def _handle_task_error(payload: dict):
    """Handle task failure / timeout from companion."""
    from server.src.models.task import Task, TaskStatus
    from server.src.models.device import Device, DeviceStatus

    task_uid = payload.get("task_uid")
    error_msg = payload.get("error", "Unknown error")
    is_timeout = payload.get("timeout", False)

    if not task_uid:
        return

    task = await Task.find_one(Task.task_uid == task_uid)
    if not task:
        logger.warning(f"task.error for unknown task_uid: {task_uid}")
        return

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.TIMEOUT if is_timeout else TaskStatus.FAILED
    task.error_message = error_msg
    task.completed_at = now
    await task.save()

    device = await Device.get(task.device_id)
    if device:
        device.status = DeviceStatus.ONLINE
        device.current_task_id = None
        await device.save()

    await broadcast_to_admins({
        "type": "task.completed",
        "timestamp": now.isoformat(),
        "payload": {
            "task_id": str(task.id),
            "task_uid": task.task_uid,
            "status": task.status.value,
            "error": error_msg,
            "device_id": str(task.device_id),
        },
    })


async def send_to_client(machine_id: str, message: dict) -> bool:
    """Send a message to a specific companion machine."""
    ws = client_connections.get(machine_id)
    if ws:
        await ws.send_json(message)
        return True
    logger.warning(f"Client not connected: {machine_id}")
    return False
