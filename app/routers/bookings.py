from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.audit import Audit
from app.core.auth import AdminUser, CurrentUser
from app.core.errors import BusinessRuleError, ForbiddenError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Booking, BookingStatus, User, UserRole
from app.schemas.booking import (
    BookingCreate,
    BookingRead,
    BookingStatusUpdate,
    BookingUpdate,
    Slot,
)
from app.schemas.common import Page
from app.services import booking_service as svc

router = APIRouter(prefix="/bookings", tags=["Записи"])


def _ensure_can_view(user: User, booking: Booking) -> None:
    allowed = (
        user.role == UserRole.ADMIN
        or (user.role == UserRole.CLIENT and booking.client_id == user.id)
        or (user.role == UserRole.MASTER and booking.master_id == user.id)
    )
    if not allowed:
        raise ForbiddenError("Немає доступу до цього запису")


def _ensure_can_set_status(user: User, booking: Booking, new_status: BookingStatus) -> None:
    """Хто який статус може ставити. Дозволені переходи перевіряє сервіс, тут лише права."""
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.MASTER:
        if booking.master_id != user.id:
            raise ForbiddenError("Статус можна змінювати лише для призначених вам записів")
        if new_status not in (BookingStatus.IN_PROGRESS, BookingStatus.DONE):
            raise ForbiddenError("Майстер може лише розпочати або завершити роботу")
        return
    # клієнт: лише скасувати власний запис
    if booking.client_id != user.id:
        raise ForbiddenError("Це не ваш запис")
    if new_status != BookingStatus.CANCELLED:
        raise ForbiddenError("Клієнт може лише скасувати власний запис")


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
def create_booking(data: BookingCreate, user: CurrentUser, db: DbSession, audit: Audit):
    if user.role == UserRole.CLIENT:
        if data.client_id not in (None, user.id):
            raise ForbiddenError("Записати можна лише себе")
        data = data.model_copy(update={"client_id": user.id})
    elif user.role == UserRole.ADMIN:
        if data.client_id is None:
            raise BusinessRuleError("Вкажіть client_id: адміністратор записує клієнта")
    else:
        raise ForbiddenError("Майстри не створюють записи")

    booking = svc.create_booking(db, data)
    audit.log(
        "booking.create", user, "booking", booking.id,
        {"total_price": str(booking.total_price), "discount_percent": str(booking.discount_percent)},
    )
    return booking


@router.get("", response_model=Page[BookingRead])
def list_bookings(
    user: CurrentUser,
    db: DbSession,
    pager: Pager,
    status_: Annotated[BookingStatus | None, Query(alias="status")] = None,
    client_id: int | None = None,
    car_id: int | None = None,
    bay_id: int | None = None,
    master_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    # Обмеження видимості накладаються примусово, незалежно від того, що передано в параметрах
    if user.role == UserRole.CLIENT:
        client_id = user.id
    elif user.role == UserRole.MASTER:
        master_id = user.id

    stmt = svc.booking_query().order_by(Booking.scheduled_at.desc(), Booking.id.desc())
    if status_:
        stmt = stmt.where(Booking.status == status_)
    if client_id is not None:
        stmt = stmt.where(Booking.client_id == client_id)
    if car_id is not None:
        stmt = stmt.where(Booking.car_id == car_id)
    if bay_id is not None:
        stmt = stmt.where(Booking.bay_id == bay_id)
    if master_id is not None:
        stmt = stmt.where(Booking.master_id == master_id)
    if date_from:
        stmt = stmt.where(Booking.scheduled_at >= svc.day_bounds(date_from)[0])
    if date_to:
        # date_to включно: беру початок наступної доби як верхню межу
        stmt = stmt.where(Booking.scheduled_at < svc.day_bounds(date_to + timedelta(days=1))[0])
    return paginate(db, stmt, pager)


# ВАЖЛИВО: цей маршрут стоїть вище за /{booking_id}, інакше FastAPI вирішить,
# що слово «availability» — це id запису, і поверне помилку валідації.
# Слоти публічні: переглянути вільний час і ціни можна ще до реєстрації
@router.get("/availability", response_model=list[Slot], summary="Вільні слоти на дату з цінами та знижками")
def availability(
    db: DbSession,
    day: Annotated[date, Query(alias="date", description="Дата у форматі РРРР-ММ-ДД")],
    service_ids: Annotated[list[int], Query(min_length=1, max_length=10)],
):
    return svc.available_slots(db, day, service_ids)


@router.get("/{booking_id}", response_model=BookingRead)
def get_booking(booking_id: int, user: CurrentUser, db: DbSession):
    booking = svc.get_booking(db, booking_id)
    _ensure_can_view(user, booking)
    return booking


@router.patch("/{booking_id}", response_model=BookingRead, summary="Призначити або зняти майстра (адміністратор)")
def update_booking(booking_id: int, data: BookingUpdate, admin: AdminUser, db: DbSession, audit: Audit):
    booking = svc.assign_master(db, booking_id, data.master_id)
    audit.log("booking.assign_master", admin, "booking", booking.id, {"master_id": data.master_id})
    return booking


@router.patch("/{booking_id}/status", response_model=BookingRead, summary="Змінити статус запису")
def update_status(booking_id: int, data: BookingStatusUpdate, user: CurrentUser, db: DbSession, audit: Audit):
    booking = svc.get_booking(db, booking_id)
    _ensure_can_set_status(user, booking, data.status)
    old = booking.status.value
    booking = svc.change_status(db, booking_id, data.status)
    audit.log("booking.status", user, "booking", booking.id, {"from": old, "to": data.status.value})
    return booking


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: int, admin: AdminUser, db: DbSession, audit: Audit):
    svc.delete_booking(db, booking_id)
    audit.log("booking.delete", admin, "booking", booking_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
