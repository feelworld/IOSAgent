from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field


class StrategyPhase(str, Enum):
    EXPLORE = "explore"
    EXECUTE = "execute"


class StrategyStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Strategy(Document):
    name: str
    script_id: Indexed(PydanticObjectId)
    script_version: int
    params: dict
    device_criteria: Optional[dict] = None
    phase: StrategyPhase
    status: StrategyStatus
    effectiveness_score: float = 0.0
    total_executions: int = 0
    successful_executions: int = 0
    total_downloads: int = 0
    explore_session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "strategies"
