from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class TaskSource(str, Enum):
    MANUAL = "manual"
    EXPLORE = "explore"
    EXECUTE = "execute"


class TaskResult(BaseModel):
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    screenshots: list[str] = Field(default_factory=list)
    download_count: int = 0
    duration_seconds: Optional[float] = None


class Task(Document):
    task_uid: Indexed(str, unique=True)
    device_id: Indexed(PydanticObjectId)
    script_id: PydanticObjectId
    script_version: int
    strategy_id: Optional[PydanticObjectId] = None
    status: TaskStatus = TaskStatus.PENDING
    params: Optional[dict] = None
    result: Optional[TaskResult] = None
    error_message: Optional[str] = None
    dispatched_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    timeout_seconds: int = 300
    retry_count: int = 0
    max_retries: int = 3
    source: TaskSource = TaskSource.MANUAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "tasks"
