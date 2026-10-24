from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import BookingStatus
from app.models.user import enum_col


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("ends_at > scheduled_at", name="ck_bookings_time_order"),
        # Під перевірку перетину слотів на конкретному посту
        Index("ix_bookings_bay_time", "bay_id", "scheduled_at", "ends_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id"), index=True)
    bay_id: Mapped[int] = mapped_column(ForeignKey("bays.id"))
    # Майстра клієнт не обирає, його призначає адмін, тому поле необов'язкове
    master_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Кінець рахуємо один раз при створенні (початок + сума тривалостей послуг)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[BookingStatus] = mapped_column(enum_col(BookingStatus), default=BookingStatus.PLANNED)
    # Підсумкова ціна вже зі знижкою «тихих годин»; сама знижка збережена окремо,
    # щоб історія була прозорою навіть після зміни правил
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["BookingService"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan"
    )
    bay: Mapped["Bay"] = relationship()  # noqa: F821
    car: Mapped["Car"] = relationship()  # noqa: F821


class BookingService(Base):
    """Зв'язок M:N «запис — послуги».

    Окрім двох ключів зберігаю ціну й тривалість на момент запису: якщо адмін потім
    змінить ціну в каталозі, старі записи не «поїдуть».
    """

    __tablename__ = "booking_services"

    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    duration_minutes: Mapped[int]

    booking: Mapped[Booking] = relationship(back_populates="items")
    service: Mapped["Service"] = relationship()  # noqa: F821
