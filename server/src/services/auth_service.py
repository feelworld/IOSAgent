from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
import bcrypt as _bcrypt

from server.src.config import settings
from server.src.models.user import User


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: str, username: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e


async def login(username: str, password: str) -> dict:
    user = await User.find_one(User.username == username)
    if not user or not verify_password(password, user.hashed_password):
        raise ValueError("Invalid username or password")

    from server.src.models.role import Role

    role = await Role.get(user.role_id) if user.role_id else None
    role_name = role.name if role else "user"

    user.last_login_at = datetime.now(timezone.utc)
    await user.save()

    access_token = create_access_token(
        user_id=str(user.id), username=user.username, role=role_name
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_hours * 3600,
    }


async def get_current_user(token: str) -> User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("Token missing user ID")

    user = await User.get(user_id)
    if not user:
        raise ValueError("User not found")
    if not user.is_active:
        raise ValueError("User is inactive")
    return user
