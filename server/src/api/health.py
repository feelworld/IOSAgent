from datetime import datetime, timezone

from fastapi import APIRouter

from server.src import db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    mongo_ok = False
    try:
        if db._client:
            await db._client.admin.command("ping")
            mongo_ok = True
    except Exception:
        pass

    status = "healthy" if mongo_ok else "unhealthy"
    return {
        "status": status,
        "mongodb": mongo_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
