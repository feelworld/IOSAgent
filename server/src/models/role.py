from datetime import datetime, timezone
from typing import Optional

from beanie import Document, Indexed
from pydantic import Field


class Role(Document):
    name: Indexed(str, unique=True)
    permissions: list[str] = Field(default=["*"])
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "roles"
