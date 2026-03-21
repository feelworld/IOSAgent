from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field
from pymongo import IndexModel, ASCENDING


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class Device(Document):
    device_uid: Indexed(str, unique=True)
    name: Optional[str] = None
    model: str
    ios_version: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    battery_level: Optional[int] = None
    network_type: Optional[str] = None
    wda_url: str
    companion_id: Indexed(str)
    current_apple_id: Optional[PydanticObjectId] = None
    group_ids: list[PydanticObjectId] = Field(default_factory=list)
    current_task_id: Optional[PydanticObjectId] = None
    last_heartbeat: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Optional[dict] = None

    # Hardware identifiers
    udid: Optional[str] = None
    serial_number: Optional[str] = None
    imei: Optional[str] = None
    meid: Optional[str] = None
    wifi_mac: Optional[str] = None
    bluetooth_mac: Optional[str] = None

    # Hardware specs
    cpu_architecture: Optional[str] = None
    hardware_platform: Optional[str] = None
    chip_id: Optional[int] = None
    product_type: Optional[str] = None

    # Jailbreak info
    jailbroken: Optional[bool] = None
    jailbreak_type: Optional[str] = None

    class Settings:
        name = "devices"
        indexes = [
            IndexModel([("status", ASCENDING), ("last_heartbeat", ASCENDING)]),
        ]
