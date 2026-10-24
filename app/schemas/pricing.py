from datetime import datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

RuleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class PricingRuleCreate(BaseModel):
    name: RuleName
    weekday: int | None = Field(default=None, ge=0, le=6, description="0 — понеділок … 6 — неділя; null — щодня")
    start_time: time
    end_time: time
    # Верхня межа 50% захищає від випадкової помилки на кшталт «99%»
    discount_percent: Decimal = Field(gt=0, le=50, max_digits=5, decimal_places=2)
    is_active: bool = True

    @model_validator(mode="after")
    def check_time_order(self):
        if self.start_time >= self.end_time:
            raise ValueError("Початок діапазону має бути раніше за його кінець")
        return self


class PricingRuleUpdate(BaseModel):
    name: RuleName | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: time | None = None
    end_time: time | None = None
    discount_percent: Decimal | None = Field(default=None, gt=0, le=50, max_digits=5, decimal_places=2)
    is_active: bool | None = None


class PricingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    weekday: int | None
    start_time: time
    end_time: time
    discount_percent: Decimal
    is_active: bool
    created_at: datetime
