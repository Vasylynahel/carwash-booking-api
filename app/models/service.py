from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import ServiceCategory
from app.models.user import enum_col


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_services_duration_positive"),
        CheckConstraint("price >= 0", name="ck_services_price_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[ServiceCategory] = mapped_column(enum_col(ServiceCategory))
    duration_minutes: Mapped[int]
    # Гроші зберігаю як Numeric, а не float, щоб не ловити 0.1 + 0.2 != 0.3
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
