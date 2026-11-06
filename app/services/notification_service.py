"""Сповіщення: зберігаються в БД і одразу надсилаються користувачеві через WebSocket.

Те, що сповіщення лежить у БД, важливо: якщо користувач був офлайн, він побачить його
після входу через GET /api/notifications, а не втратить.
"""
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Booking, BookingStatus, Notification, NotificationPriority, User, UserRole
from app.realtime import publisher


@dataclass
class Draft:
    user_id: int
    type: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    booking_id: int | None = None


def payload(n: Notification) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "priority": n.priority.value,
        "message": n.message,
        "booking_id": n.booking_id,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat() if n.created_at else datetime.now(UTC).isoformat(),
    }


def notify_many(db: Session, drafts: list[Draft]) -> list[Notification]:
    """Пакетне надсилання: усі сповіщення записуються одним запитом і однією транзакцією."""
    if not drafts:
        return []
    rows = [
        Notification(
            user_id=d.user_id, type=d.type, message=d.message, priority=d.priority, booking_id=d.booking_id
        )
        for d in drafts
    ]
    db.add_all(rows)
    db.commit()
    for n in rows:
        publisher.emit("notification", payload(n), [f"user:{n.user_id}"])
    return rows


def _admin_ids(db: Session) -> list[int]:
    return list(db.scalars(select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True))))


def _when(booking: Booking) -> str:
    dt = booking.scheduled_at
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return dt.astimezone(settings.tz).strftime("%d.%m о %H:%M")


def on_booking_created(db: Session, booking: Booking) -> None:
    price = f"{booking.total_price} грн"
    if booking.discount_percent and booking.discount_percent > 0:
        price += f", знижка тихих годин {booking.discount_percent.normalize():f}%"
    drafts = [
        Draft(
            booking.client_id, "booking_created",
            f"Запис №{booking.id} підтверджено на {_when(booking)}. До сплати: {price}.",
            NotificationPriority.NORMAL, booking.id,
        )
    ]
    drafts += [
        Draft(admin_id, "booking_created", f"Новий запис №{booking.id} на {_when(booking)}.",
              NotificationPriority.LOW, booking.id)
        for admin_id in _admin_ids(db)
    ]
    notify_many(db, drafts)


def on_status_changed(db: Session, booking: Booking, actor: User, new_status: BookingStatus) -> None:
    n = booking.id
    drafts: list[Draft] = []

    if new_status == BookingStatus.IN_PROGRESS:
        drafts.append(Draft(booking.client_id, "booking_status", f"Запис №{n}: роботу над вашим авто розпочато.",
                            NotificationPriority.NORMAL, n))
    elif new_status == BookingStatus.DONE:
        drafts.append(Draft(booking.client_id, "booking_status", f"Запис №{n}: роботу завершено. Дякуємо!",
                            NotificationPriority.NORMAL, n))
    elif new_status == BookingStatus.CANCELLED:
        if actor.id == booking.client_id:
            drafts.append(Draft(booking.client_id, "booking_cancelled", f"Ви скасували запис №{n}.",
                                NotificationPriority.NORMAL, n))
        else:
            drafts.append(Draft(booking.client_id, "booking_cancelled", f"Запис №{n} скасовано адміністратором.",
                                NotificationPriority.HIGH, n))
        text = f"Запис №{n} на {_when(booking)} скасовано."
        if actor.id == booking.client_id:
            drafts += [Draft(a, "booking_cancelled", text, NotificationPriority.NORMAL, n) for a in _admin_ids(db)]
        if booking.master_id and booking.master_id != actor.id:
            drafts.append(Draft(booking.master_id, "booking_cancelled", text, NotificationPriority.NORMAL, n))

    if actor.role == UserRole.MASTER:
        drafts += [
            Draft(a, "booking_status", f"Майстер {actor.full_name} змінив статус запису №{n}.",
                  NotificationPriority.LOW, n)
            for a in _admin_ids(db)
        ]
    notify_many(db, drafts)


def on_master_assigned(db: Session, booking: Booking) -> None:
    if booking.master_id is None:
        return
    master = db.get(User, booking.master_id)
    notify_many(
        db,
        [
            Draft(booking.master_id, "master_assigned", f"Вам призначено запис №{booking.id} на {_when(booking)}.",
                  NotificationPriority.HIGH, booking.id),
            Draft(booking.client_id, "master_assigned",
                  f"Для запису №{booking.id} призначено майстра: {master.full_name}.",
                  NotificationPriority.LOW, booking.id),
        ],
    )
