from datetime import datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BookingStatus
from app.schemas.service import ServiceShort


class BookingCreate(BaseModel):
    # Клієнт не передає це поле (береться з токена); адміністратор записує клієнта за його id
    client_id: int | None = None
    car_id: int
    service_ids: list[int] = Field(min_length=1, max_length=10)
    # AwareDatetime вимагає часовий пояс («2026-10-25T10:00:00+03:00»): без нього час неоднозначний
    scheduled_at: AwareDatetime
    bay_id: int | None = None      # якщо не вказано, пост підбирається автоматично
    master_id: int | None = None   # зазвичай призначає адмін уже після створення

    @field_validator("service_ids")
    @classmethod
    def no_duplicates(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("Послуги в запису не повинні повторюватися")
        return v


class BookingUpdate(BaseModel):
    """Змінити через PATCH можна лише майстра. Час і послуги — через скасування й новий запис."""

    master_id: int | None = None


class BookingStatusUpdate(BaseModel):
    status: BookingStatus


class BookingItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service: ServiceShort
    price: Decimal
    duration_minutes: int


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Клієнт не передає це поле (береться з токена); адміністратор записує клієнта за його id
    client_id: int | None = None
    car_id: int
    bay_id: int
    master_id: int | None
    scheduled_at: datetime
    ends_at: datetime
    status: BookingStatus
    total_price: Decimal            # підсумок уже зі знижкою
    discount_percent: Decimal       # знижка «тихих годин», 0 — якщо не діяла
    created_at: datetime
    items: list[BookingItemRead]


class Slot(BaseModel):
    start: datetime
    end: datetime
    free_bays: int
    base_price: Decimal                 # ціна без знижки
    price: Decimal                      # ціна, яку заплатить клієнт, обравши цей слот
    discount_percent: Decimal
    rule_name: str | None = None        # яке правило дало знижку («Будні вранці»)
