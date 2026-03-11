from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from server.src.models.role import Role
from server.src.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer()


class LoginRequest(BaseModel):
    username: str
    password: str


def _ok(data: dict | list | None = None, message: str = "success") -> dict:
    return {"code": 0, "message": message, "data": data}


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
):
    try:
        return await auth_service.get_current_user(credentials.credentials)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.post("/login")
async def login(body: LoginRequest):
    try:
        result = await auth_service.login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return _ok(result)


@router.get("/me")
async def me(user=Depends(get_current_user)):
    role = await Role.get(user.role_id) if user.role_id else None
    data = {
        "id": str(user.id),
        "username": user.username,
        "is_active": user.is_active,
        "role": role.name if role else None,
        "permissions": role.permissions if role else [],
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat(),
    }
    return _ok(data)
