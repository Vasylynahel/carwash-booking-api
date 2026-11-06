"""Відправка подій клієнтам із звичайних (синхронних) ендпоїнтів REST.

Ендпоїнти FastAPI виконуються в робочих потоках, а Socket.IO працює в циклі подій,
тому викликаємо його через anyio.from_thread. Збій розсилки не повинен ламати основну
операцію: запис уже збережено, і найгірший наслідок — клієнт оновиться після перезавантаження.
"""
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

import anyio.from_thread
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.observability import WS_EVENTS
from app.models import Booking, UserRole
from app.realtime import events as event_store
from app.realtime.sio import sio

log = logging.getLogger("carwash.realtime")


async def _emit(event: str, envelope: dict, room: str) -> None:
    await sio.emit(event, envelope, room=room)
    WS_EVENTS.labels(event).inc()


def emit(
    event: str,
    data: dict,
    rooms: Sequence[str],
    db: Session | None = None,
    persist: bool = False,
) -> None:
    """Надсилає подію в кімнати. З persist=True ще й записує її в журнал для відновлення після обриву."""
    rooms = list(dict.fromkeys(rooms))  # без дублікатів, порядок зберігаємо
    if not rooms:
        return
    try:
        ids: dict[str, int | None] = {room: None for room in rooms}
        if persist and db is not None:
            ids = dict(event_store.store(db, rooms, event, data))
        for room in rooms:
            anyio.from_thread.run(_emit, event, {"id": ids[room], "data": data}, room)
    except Exception:
        log.exception("Не вдалося розіслати подію %s", event)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def local_date(dt: datetime) -> str:
    return _utc(dt).astimezone(settings.tz).date().isoformat()


def booking_payload(b: Booking) -> dict:
    return {
        "id": b.id,
        "status": b.status.value,
        "client_id": b.client_id,
        "car_id": b.car_id,
        "bay_id": b.bay_id,
        "master_id": b.master_id,
        "scheduled_at": _utc(b.scheduled_at).isoformat(),
        "ends_at": _utc(b.ends_at).isoformat(),
        "total_price": str(b.total_price),
        "discount_percent": str(b.discount_percent),
    }


def publish_booking(db: Session, event: str, booking: Booking) -> None:
    """booking:created | booking:updated | booking:status | booking:deleted

    Отримують: клієнт запису, призначений майстер і всі адміністратори. Додатково
    повідомляємо тих, хто дивиться вільні слоти на цю дату, що вони змінилися.
    """
    rooms = [f"user:{booking.client_id}", f"role:{UserRole.ADMIN.value}"]
    if booking.master_id:
        rooms.append(f"user:{booking.master_id}")
    emit(event, booking_payload(booking), rooms, db=db, persist=True)

    day = local_date(booking.scheduled_at)
    emit("slots:changed", {"date": day}, [f"slots:{day}"])


def publish_catalog(entity: str, entity_id: int | None, action: str) -> None:
    """Каталог змінився (послуга, пост, правило знижки): клієнти оновлюють ціни й слоти."""
    emit("catalog:changed", {"entity": entity, "id": entity_id, "action": action}, ["all"])
