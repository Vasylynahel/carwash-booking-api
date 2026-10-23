from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

Brand = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


def _normalize_plate(value: str) -> str:
    # «ка 1234 ав» і «KA1234AB» — один і той самий номер, тому приводжу до єдиного вигляду
    return value.replace(" ", "").replace("-", "").upper()


class CarBase(BaseModel):
    brand: Brand
    model: Brand
    plate_number: str

    @field_validator("plate_number")
    @classmethod
    def check_plate(cls, v: str) -> str:
        v = _normalize_plate(v)
        if not (3 <= len(v) <= 12 and v.isalnum()):
            raise ValueError("Державний номер має містити 3–12 літер або цифр")
        return v


class CarCreate(CarBase):
    # У лабі 2 власника братимемо з токена, а поки він передається явно
    owner_id: int


class CarUpdate(BaseModel):
    brand: Brand | None = None
    model: Brand | None = None
    plate_number: str | None = None

    @field_validator("plate_number")
    @classmethod
    def check_plate(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return CarBase.check_plate(v)


class CarRead(CarBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
