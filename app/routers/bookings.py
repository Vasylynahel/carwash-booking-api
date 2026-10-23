from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Booking, BookingStatus
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


@router.post("", response_model=BookingRead, status_code=status.HTTP_201_CREATED)
def create_booking(data: BookingCreate, db: DbSession):
    return svc.create_booking(db, data)


@router.get("", response_model=Page[BookingRead])
def list_bookings(
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
# що слово «availability» — це id запису, і поверне помилку валідації
@router.get("/availability", response_model=list[Slot], summary="Вільні слоти на дату")
def availability(
    db: DbSession,
    day: Annotated[date, Query(alias="date", description="Дата у форматі РРРР-ММ-ДД")],
    service_ids: Annotated[list[int], Query(min_length=1, max_length=10)],
):
    return svc.available_slots(db, day, service_ids)


@router.get("/{booking_id}", response_model=BookingRead)
def get_booking(booking_id: int, db: DbSession):
    return svc.get_booking(db, booking_id)


@router.patch("/{booking_id}", response_model=BookingRead, summary="Призначити або зняти майстра")
def update_booking(booking_id: int, data: BookingUpdate, db: DbSession):
    return svc.assign_master(db, booking_id, data.master_id)


@router.patch("/{booking_id}/status", response_model=BookingRead, summary="Змінити статус запису")
def update_status(booking_id: int, data: BookingStatusUpdate, db: DbSession):
    return svc.change_status(db, booking_id, data.status)


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: int, db: DbSession):
    svc.delete_booking(db, booking_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
