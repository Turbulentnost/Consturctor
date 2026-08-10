from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.schemas.auth import LoginRequest, LoginResponse, UserFioListResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/users", response_model=UserFioListResponse)
async def list_users(search: str | None = None) -> UserFioListResponse:
    try:
        items = await auth_service.list_user_fios(search)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return UserFioListResponse(items=items)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    try:
        return await auth_service.login(body.fio, body.password)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/me", response_model=UserOut)
async def me(auth: AuthContext = Depends(get_current_user)) -> UserOut:
    try:
        return await auth_service.get_current_user_profile(auth.user_id, auth.fio)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
