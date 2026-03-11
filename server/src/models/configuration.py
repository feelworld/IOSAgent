from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, ASCENDING


class ConfigScope(str, Enum):
    GLOBAL = "global"
    DEVICE_GROUP = "device_group"
    DEVICE = "device"


class Configuration(Document):
    key: str
    value: Any
    scope: ConfigScope
    scope_id: Optional[PydanticObjectId] = None
    description: Optional[str] = None
    updated_by: Optional[PydanticObjectId] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "configurations"
        indexes = [
            IndexModel(
                [("key", ASCENDING), ("scope", ASCENDING), ("scope_id", ASCENDING)],
                unique=True,
            ),
        ]
