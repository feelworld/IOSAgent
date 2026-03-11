from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class CompanionStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"


class CompanionMachine(Document):
    machine_id: Indexed(str, unique=True)
    name: Optional[str] = None
    ip_address: Optional[str] = None
    status: CompanionStatus = CompanionStatus.OFFLINE
    managed_device_ids: list[PydanticObjectId] = Field(default_factory=list)
    max_devices: int = 20
    last_heartbeat: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "companion_machines"
