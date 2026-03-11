from datetime import datetime, timezone
from typing import Optional

from beanie import Document
from pydantic import Field


class AuditLog(Document):
    user_id: Optional[str] = None
    username: Optional[str] = None
    method: str
    path: str
    status_code: int
    request_body: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ip_address: Optional[str] = None

    class Settings:
        name = "audit_logs"
