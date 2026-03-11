from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from beanie import Document, Indexed, PydanticObjectId
from pydantic import BaseModel, Field


class ScriptType(str, Enum):
    STEPS = "steps"
    PYTHON = "python"


class ScriptStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"


class ScriptStep(BaseModel):
    action: str
    target: Optional[str] = None
    params: Optional[dict] = None
    timeout: int = 30


class Script(Document):
    name: Indexed(str)
    description: Optional[str] = None
    script_type: ScriptType = ScriptType.STEPS
    current_version: int = 1
    status: ScriptStatus = ScriptStatus.DRAFT
    created_by: Optional[PydanticObjectId] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "scripts"


class ScriptVersion(Document):
    script_id: Indexed(PydanticObjectId)
    version: int
    script_type: ScriptType = ScriptType.STEPS
    steps: list[ScriptStep] = Field(default_factory=list)
    python_code: Optional[str] = None
    changelog: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "script_versions"
