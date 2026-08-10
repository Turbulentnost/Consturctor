from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    fio: str = Field(..., min_length=1, description="ФИО пользователя из 1С")
    password: str = Field(..., min_length=1)


class UserOut(BaseModel):
    id: str
    fio: str
    department: str = ""


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserFioListResponse(BaseModel):
    items: list[str]
