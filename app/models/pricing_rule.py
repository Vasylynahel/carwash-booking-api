from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Numeric, SmallInteger, String, Time, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PricingRule(Base):
    """Правило «тихих годин»: знижка на певні години (і, за потреби, день тижня).

    weekday: 0 = понеділок … 6 = неділя; NULL означає «щодня».
    Година кінця не входить у діапазон: правило 10:00–14:00 діє для запису о 13:30, але не о 14:00.
    """

    __tablename__ = "pricing_rules"
    __table_args__ = (
        CheckConstraint("start_time < end_time", name="ck_pricing_rules_time_order"),
        CheckConstraint("discount_percent > 0 AND discount_percent <= 50", name="ck_pricing_rules_discount"),
        CheckConstraint("weekday IS NULL OR (weekday >= 0 AND weekday <= 6)", name="ck_pricing_rules_weekday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    weekday: Mapped[int | None] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
