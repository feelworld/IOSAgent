import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from beanie import PydanticObjectId
from beanie.operators import In

from server.src.models.task import Task, TaskSource, TaskStatus
from server.src.services import command_dispatcher

logger = logging.getLogger(__name__)


async def batch_dispatch(
    device_ids: list[PydanticObjectId],
    script_id: PydanticObjectId,
    script_version: int,
    params: Optional[dict] = None,
    timeout_seconds: int = 300,
    source: TaskSource = TaskSource.MANUAL,
) -> list[Task]:
    """Dispatch a command to multiple devices."""
    tasks: list[Task] = []
    for device_id in device_ids:
        try:
            task = await command_dispatcher.dispatch_command(
                device_id=device_id,
                script_id=script_id,
                script_version=script_version,
                params=params,
                timeout_seconds=timeout_seconds,
                source=source,
            )
            tasks.append(task)
        except Exception as e:
            logger.error(f"Failed to dispatch to device {device_id}: {e}")
    return tasks


async def cleanup_expired_tasks(expire_seconds: int = 3600) -> int:
    """Mark stale pending/dispatched tasks as failed."""
    threshold = datetime.now(timezone.utc) - timedelta(seconds=expire_seconds)
    expired = await Task.find(
        In(Task.status, [TaskStatus.PENDING, TaskStatus.DISPATCHED]),
        Task.created_at < threshold,
    ).to_list()

    count = 0
    for task in expired:
        task.status = TaskStatus.FAILED
        task.error_message = "Command expired"
        task.completed_at = datetime.now(timezone.utc)
        await task.save()
        count += 1

    if count:
        logger.info(f"Cleaned up {count} expired task(s)")
    return count
