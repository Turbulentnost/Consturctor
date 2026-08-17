from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.schemas.auth import (
    DepartmentListResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UpdateDepartmentRequest,
    UserFioListResponse,
    UserOut,
)
from app.services import app_users, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/users", response_model=UserFioListResponse)
async def list_users(search: str | None = None) -> UserFioListResponse:
    try:
        items = await auth_service.list_user_fios(search)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return UserFioListResponse(items=items)


@router.get("/departments", response_model=DepartmentListResponse)
async def departments(_: AuthContext = Depends(get_current_user)) -> DepartmentListResponse:
    try:
        items = await auth_service.list_department_names()
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return DepartmentListResponse(items=items)


@router.post("/register", response_model=LoginResponse)
async def register(body: RegisterRequest) -> LoginResponse:
    try:
        return await auth_service.register(body.fio, body.password, body.department)
    except auth_service.AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


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


@router.patch("/me/department", response_model=UserOut)
async def update_my_department(
    body: UpdateDepartmentRequest,
    auth: AuthContext = Depends(get_current_user),
) -> UserOut:
    try:
        app_user = app_users.update_user_department(
            user_id=auth.user_id,
            department=body.department,
        )
    except app_users.DepartmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return app_users.to_user_out(app_user)


@router.get("/users/{user_id}/avatar")
async def get_user_avatar(user_id: str) -> FileResponse:
    path = app_users.resolve_avatar_file(user_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Аватар не найден")
    return FileResponse(path)


@router.post("/me/avatar", response_model=UserOut)
async def upload_my_avatar(
    auth: AuthContext = Depends(get_current_user),
    file: UploadFile = File(...),
) -> UserOut:
    data = await file.read()
    try:
        app_user = app_users.save_user_avatar(
            user_id=auth.user_id,
            data=data,
            filename=file.filename or "avatar.png",
        )
    except app_users.AvatarError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    return app_users.to_user_out(app_user)
