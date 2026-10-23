"""Уся логіка запису в одному місці: розрахунок часу, пошук вільного поста, перевірка перетинів.

Роутер лише приймає запит і віддає відповідь, а правила предметної області живуть тут.
"""
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Bay, Booking, BookingService, BookingStatus, Car, Service, User, UserRole
from app.schemas.booking import BookingCreate, Slot

# Які переходи статусів дозволені. «Виконано» і «скасовано» — фінальні.
ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PLANNED: {BookingStatus.IN_PROGRESS, BookingStatus.CANCELLED},
    BookingStatus.IN_PROGRESS: {BookingStatus.DONE, BookingStatus.CANCELLED},
    BookingStatus.DONE: set(),
    BookingStatus.CANCELLED: set(),
}


def _utc(dt: datetime) -> datetime:
    # SQLite (у тестах) віддає дати без пояса, Postgres — із поясом; приводжу до одного вигляду
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def booking_query() -> Select:
    # selectinload одразу підтягує послуги пачкою запитів, тож N+1 не буде
    return select(Booking).options(
        selectinload(Booking.items).selectinload(BookingService.service)
    )


def get_booking(db: Session, booking_id: int) -> Booking:
    booking = db.scalar(booking_query().where(Booking.id == booking_id))
    if booking is None:
        raise NotFoundError("Запис не знайдено")
    return booking


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Початок і кінець робочого дня за місцевим часом, у UTC."""
    tz = settings.tz
    start = datetime.combine(day, time(settings.work_day_start), tzinfo=tz)
    end = datetime.combine(day, time(settings.work_day_end), tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def _overlap_filter(start: datetime, end: datetime):
    # Два проміжки перетинаються, якщо кожен починається раніше, ніж закінчується інший.
    # Дотик кінця до початку (10:00–11:00 і 11:00–12:00) перетином не вважається.
    return (
        Booking.scheduled_at < end,
        Booking.ends_at > start,
        Booking.status != BookingStatus.CANCELLED,
    )


def _is_busy(db: Session, column, value: int, start: datetime, end: datetime) -> bool:
    stmt = select(Booking.id).where(column == value, *_overlap_filter(start, end)).limit(1)
    return db.scalar(stmt) is not None


def _load_services(db: Session, service_ids: list[int]) -> list[Service]:
    services = db.scalars(select(Service).where(Service.id.in_(service_ids))).all()
    found = {s.id for s in services}
    missing = sorted(set(service_ids) - found)
    if missing:
        raise NotFoundError(f"Послуги не знайдено: {missing}")
    inactive = [s.name for s in services if not s.is_active]
    if inactive:
        raise BusinessRuleError(f"Послуги тимчасово недоступні: {', '.join(inactive)}")
    return list(services)


def _check_working_hours(start: datetime, end: datetime) -> None:
    local_start = start.astimezone(settings.tz)
    open_at, close_at = day_bounds(local_start.date())
    if start < open_at or end > close_at:
        raise BusinessRuleError(
            f"Запис має повністю вкладатися в робочий день {settings.work_day_start}:00–{settings.work_day_end}:00"
        )


def create_booking(db: Session, data: BookingCreate) -> Booking:
    client = db.get(User, data.client_id)
    if client is None:
        raise NotFoundError("Клієнта не знайдено")
    if client.role != UserRole.CLIENT or not client.is_active:
        raise BusinessRuleError("Записувати можна лише активного користувача з роллю «клієнт»")

    car = db.get(Car, data.car_id)
    if car is None:
        raise NotFoundError("Автомобіль не знайдено")
    if car.owner_id != client.id:
        raise BusinessRuleError("Цей автомобіль належить іншому клієнту")

    services = _load_services(db, data.service_ids)
    total_minutes = sum(s.duration_minutes for s in services)
    total_price: Decimal = sum((s.price for s in services), Decimal("0"))

    start = _utc(data.scheduled_at)
    end = start + timedelta(minutes=total_minutes)

    if start <= datetime.now(UTC):
        raise BusinessRuleError("Не можна записатися на час, який уже минув")
    _check_working_hours(start, end)

    # Блокую рядки постів (SELECT ... FOR UPDATE): якщо двоє клієнтів одночасно
    # хочуть один слот, другий запит дочекається першого й уже побачить його запис.
    # Без цього обидві перевірки «вільно» могли б пройти одночасно (подвійне бронювання).
    bays = db.scalars(
        select(Bay).where(Bay.is_active.is_(True)).order_by(Bay.id).with_for_update()
    ).all()

    if data.bay_id is not None:
        bay = next((b for b in bays if b.id == data.bay_id), None)
        if bay is None:
            raise NotFoundError("Активний пост із таким id не знайдено")
        if _is_busy(db, Booking.bay_id, bay.id, start, end):
            raise ConflictError("Обраний пост у цей час уже зайнятий")
    else:
        bay = next((b for b in bays if not _is_busy(db, Booking.bay_id, b.id, start, end)), None)
        if bay is None:
            raise ConflictError("На цей час немає вільних постів")

    if data.master_id is not None:
        _check_master_free(db, data.master_id, start, end)

    # Один автомобіль не може бути на двох постах одночасно
    if _is_busy(db, Booking.car_id, car.id, start, end):
        raise ConflictError("На цей час для автомобіля вже є запис")

    booking = Booking(
        client_id=client.id,
        car_id=car.id,
        bay_id=bay.id,
        master_id=data.master_id,
        scheduled_at=start,
        ends_at=end,
        total_price=total_price,
        status=BookingStatus.PLANNED,
        items=[
            BookingService(service_id=s.id, price=s.price, duration_minutes=s.duration_minutes)
            for s in services
        ],
    )
    db.add(booking)
    db.commit()
    return get_booking(db, booking.id)


def _check_master_exists(db: Session, master_id: int) -> None:
    master = db.get(User, master_id)
    if master is None:
        raise NotFoundError("Майстра не знайдено")
    if master.role != UserRole.MASTER or not master.is_active:
        raise BusinessRuleError("Призначити можна лише активного користувача з роллю «майстер»")


def _check_master_free(db: Session, master_id: int, start: datetime, end: datetime) -> None:
    _check_master_exists(db, master_id)
    if _is_busy(db, Booking.master_id, master_id, start, end):
        raise ConflictError("Майстер у цей час зайнятий іншим записом")


def assign_master(db: Session, booking_id: int, master_id: int | None) -> Booking:
    booking = get_booking(db, booking_id)
    if booking.status in (BookingStatus.DONE, BookingStatus.CANCELLED):
        raise ConflictError("Для завершеного чи скасованого запису майстра змінити не можна")
    if master_id is not None:
        start, end = _utc(booking.scheduled_at), _utc(booking.ends_at)
        stmt = select(Booking.id).where(
            Booking.master_id == master_id, Booking.id != booking.id, *_overlap_filter(start, end)
        ).limit(1)
        _check_master_exists(db, master_id)
        if db.scalar(stmt) is not None:
            raise ConflictError("Майстер у цей час зайнятий іншим записом")
    booking.master_id = master_id
    db.commit()
    return get_booking(db, booking_id)


def change_status(db: Session, booking_id: int, new_status: BookingStatus) -> Booking:
    booking = get_booking(db, booking_id)
    if new_status not in ALLOWED_TRANSITIONS[booking.status]:
        raise ConflictError(
            f"Перехід зі статусу «{booking.status.value}» у «{new_status.value}» неможливий"
        )
    booking.status = new_status
    db.commit()
    return get_booking(db, booking_id)


def delete_booking(db: Session, booking_id: int) -> None:
    booking = get_booking(db, booking_id)
    # Історію не стираю: видалити можна лише скасований запис
    if booking.status != BookingStatus.CANCELLED:
        raise ConflictError("Видалити можна лише скасований запис; спочатку скасуйте його")
    db.delete(booking)
    db.commit()


def available_slots(db: Session, day: date, service_ids: list[int]) -> list[Slot]:
    """Вільні стартові часи на добу для обраних послуг.

    Один запит за записами доби, далі все рахується в пам'яті, тож не робимо запит на кожен слот.
    """
    services = _load_services(db, service_ids)
    duration = timedelta(minutes=sum(s.duration_minutes for s in services))
    open_at, close_at = day_bounds(day)

    bay_ids = db.scalars(select(Bay.id).where(Bay.is_active.is_(True))).all()
    rows = db.execute(
        select(Booking.bay_id, Booking.scheduled_at, Booking.ends_at).where(
            *_overlap_filter(open_at, close_at)
        )
    ).all()
    busy = [(b, _utc(s), _utc(e)) for b, s, e in rows]

    now = datetime.now(UTC)
    step = timedelta(minutes=settings.slot_step_minutes)
    slots: list[Slot] = []
    cursor = open_at
    while cursor + duration <= close_at:
        end = cursor + duration
        if cursor > now:
            free = sum(
                1
                for bay_id in bay_ids
                if not any(b == bay_id and s < end and e > cursor for b, s, e in busy)
            )
            if free:
                slots.append(
                    Slot(
                        start=cursor.astimezone(settings.tz),
                        end=end.astimezone(settings.tz),
                        free_bays=free,
                    )
                )
        cursor += step
    return slots
