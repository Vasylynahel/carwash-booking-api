from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

from app.models.enums import UserRole

Phone = Annotated[str, StringConstraints(pattern=r"^\+380\d{9}$")]
FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]


class UserCreate(BaseModel):
    email: EmailStr
    password: Password
    full_name: FullName
    phone: Phone | None = None
    role: UserRole = UserRole.CLIENT


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    password: Password | None = None
    full_name: FullName | None = None
    phone: Phone | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserRead(BaseModel):
    # password_hash тут навмисно немає: хеш не повинен виходити за межі сервера
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
