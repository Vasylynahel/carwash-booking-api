from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Event(Base):
    """Журнал подій реального часу з наскрізним номером (id).

    Якщо клієнт втратив з'єднання, після перепідключення він передає номер останньої
    отриманої події, і сервер віддає все, що було пропущено.
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_room_id", "room", "id"),)

    # BigInteger у Postgres, Integer у SQLite (там автоінкремент працює лише для Integer)
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    room: Mapped[str] = mapped_column(String(60))
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
