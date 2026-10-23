from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Bay(Base):
    """Пост обслуговування — фізичний ресурс, який у кожен момент часу може бути зайнятий лише одним записом."""

    __tablename__ = "bays"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
