from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StoredFile(Base):
    """Запис про завантажений файл. Сам файл лежить на диску під випадковим іменем."""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(100), unique=True)  # ім'я на диску (uuid + розширення)
    original_name: Mapped[str] = mapped_column(String(255))          # лише для показу користувачу
    mimetype: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Необов'язково: фото, прикріплене до автомобіля
    car_id: Mapped[int | None] = mapped_column(ForeignKey("cars.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
