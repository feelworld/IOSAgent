from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class AppleAccountStatus(str, Enum):
    ACTIVE = "active"
    BANNED = "banned"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class AppleAccount(Document):
    email: Indexed(str, unique=True)
    encrypted_password: str
    status: AppleAccountStatus = AppleAccountStatus.UNKNOWN
    bound_device_id: Optional[PydanticObjectId] = None
    is_primary: bool = False
    pool_group: Indexed(str)
    last_used_at: Optional[datetime] = None
    banned_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "apple_accounts"
