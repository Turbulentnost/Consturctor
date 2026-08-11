from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    fio: str = Field(..., min_length=1, description="ФИО пользователя из 1С")
    password: str = Field(..., min_length=1)


class UserOut(BaseModel):
    id: str
    fio: str
    department: str = ""
    avatar_url: str | None = None
    can_change_department: bool = True
    department_change_available_at: datetime | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserFioListResponse(BaseModel):
    items: list[str]


class DepartmentListResponse(BaseModel):
    items: list[str]


class UpdateDepartmentRequest(BaseModel):
    department: str = Field(..., min_length=1, max_length=512)
