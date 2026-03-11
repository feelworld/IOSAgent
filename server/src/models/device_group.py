from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class DeviceGroup(Document):
    name: Indexed(str, unique=True)
    description: Optional[str] = None
    device_ids: list[PydanticObjectId] = Field(default_factory=list)
    config_overrides: Optional[dict] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "device_groups"
