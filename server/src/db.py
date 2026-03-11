import logging
from urllib.parse import urlparse

import motor.motor_asyncio
from beanie import init_beanie
import bcrypt as _bcrypt

from server.src.config import settings
from server.src.models import ALL_MODELS
from server.src.models.role import Role
from server.src.models.user import User

logger = logging.getLogger(__name__)

_client: motor.motor_asyncio.AsyncIOMotorClient | None = None


def _extract_db_name(url: str) -> str:
    parsed = urlparse(url)
    db_name = parsed.path.lstrip("/")
    return db_name if db_name else "ios_ranking"


async def init_db() -> None:
    global _client
    _client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongodb_url)
    db = _client[_extract_db_name(settings.mongodb_url)]
    await init_beanie(database=db, document_models=ALL_MODELS)
    logger.info("MongoDB connected, Beanie initialized")
    await _seed_defaults()


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("MongoDB connection closed")


async def _seed_defaults() -> None:
    admin_role = await Role.find_one(Role.name == "admin")
    if not admin_role:
        admin_role = Role(name="admin", permissions=["*"], description="Super administrator")
        await admin_role.insert()
        logger.info("Default admin role created")

    admin_user = await User.find_one(User.username == "admin")
    if not admin_user:
        hashed_pw = _bcrypt.hashpw(b"admin123", _bcrypt.gensalt()).decode()
        admin_user = User(
            username="admin",
            hashed_password=hashed_pw,
            role_id=admin_role.id,
        )
        await admin_user.insert()
        logger.info("Default admin user created (username=admin)")
