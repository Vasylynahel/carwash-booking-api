from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import NotificationPriority
from app.models.user import enum_col


class Notification(Base):
    """Персональне сповіщення. Зберігається в БД і одночасно летить користувачеві через WebSocket."""

    __tablename__ = "notifications"
    __table_args__ = (
        # Типовий запит: «мої непрочитані, найновіші зверху»
        Index("ix_notifications_user_read_created", "user_id", "is_read", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"))
    # Тип дозволяє клієнту обрати іконку чи дію: booking_created, booking_status, master_assigned тощо
    type: Mapped[str] = mapped_column(String(30), default="info", server_default="info")
    priority: Mapped[NotificationPriority] = mapped_column(
        enum_col(NotificationPriority),
        default=NotificationPriority.NORMAL,
        server_default="normal",
    )
    message: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
