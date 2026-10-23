from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.enums import ServiceCategory

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class ServiceCreate(BaseModel):
    name: Name
    description: str | None = Field(default=None, max_length=2000)
    category: ServiceCategory
    duration_minutes: int = Field(gt=0, le=720)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    is_active: bool = True


class ServiceUpdate(BaseModel):
    name: Name | None = None
    description: str | None = Field(default=None, max_length=2000)
    category: ServiceCategory | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=720)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    is_active: bool | None = None


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    category: ServiceCategory
    duration_minutes: int
    price: Decimal
    is_active: bool


class ServiceShort(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
