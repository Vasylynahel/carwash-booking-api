from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

BayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class BayCreate(BaseModel):
    name: BayName
    is_active: bool = True


class BayUpdate(BaseModel):
    name: BayName | None = None
    is_active: bool | None = None


class BayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
