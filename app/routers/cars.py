from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.core.audit import Audit
from app.core.auth import CurrentUser
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Car, User, UserRole
from app.schemas.car import CarCreate, CarRead, CarUpdate
from app.schemas.common import Page

router = APIRouter(prefix="/cars", tags=["Автомобілі"])


def _get_or_404(db, car_id: int, user: User | None = None) -> Car:
    car = db.get(Car, car_id)
    if car is None:
        raise NotFoundError("Автомобіль не знайдено")
    # Клієнт бачить і змінює лише власні автомобілі; персонал — усі
    if user is not None and user.role == UserRole.CLIENT and car.owner_id != user.id:
        raise ForbiddenError("Це не ваш автомобіль")
    return car


def _ensure_plate_free(db, plate: str, exclude_id: int | None = None) -> None:
    stmt = select(Car.id).where(Car.plate_number == plate)
    if exclude_id is not None:
        stmt = stmt.where(Car.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise ConflictError("Автомобіль із таким номером уже зареєстрований")


@router.post("", response_model=CarRead, status_code=status.HTTP_201_CREATED)
def create_car(data: CarCreate, user: CurrentUser, db: DbSession, audit: Audit):
    if user.role == UserRole.CLIENT:
        owner_id = user.id  # клієнт додає автомобіль лише собі, чужий owner_id ігнорується
    elif data.owner_id is None:
        raise BusinessRuleError("Для адміністратора й майстра потрібно вказати owner_id")
    else:
        owner_id = data.owner_id
        if db.get(User, owner_id) is None:
            raise NotFoundError("Власника не знайдено")
    _ensure_plate_free(db, data.plate_number)
    car = Car(**data.model_dump(exclude={"owner_id"}), owner_id=owner_id)
    db.add(car)
    db.commit()
    audit.log("car.create", user, "car", car.id)
    return car


@router.get("", response_model=Page[CarRead])
def list_cars(
    user: CurrentUser,
    db: DbSession,
    pager: Pager,
    owner_id: int | None = None,
    search: Annotated[str | None, Query(max_length=60, description="Марка, модель або номер")] = None,
):
    stmt = select(Car).order_by(Car.id)
    if user.role == UserRole.CLIENT:
        owner_id = user.id  # фільтр примусовий: клієнт не може побачити чужі авто
    if owner_id is not None:
        stmt = stmt.where(Car.owner_id == owner_id)
    if search:
        p = f"%{search}%"
        stmt = stmt.where(Car.brand.ilike(p) | Car.model.ilike(p) | Car.plate_number.ilike(p.upper()))
    return paginate(db, stmt, pager)


@router.get("/{car_id}", response_model=CarRead)
def get_car(car_id: int, user: CurrentUser, db: DbSession):
    return _get_or_404(db, car_id, user)


@router.patch("/{car_id}", response_model=CarRead)
def update_car(car_id: int, data: CarUpdate, user: CurrentUser, db: DbSession, audit: Audit):
    car = _get_or_404(db, car_id, user)
    changes = data.model_dump(exclude_unset=True)
    if "plate_number" in changes:
        _ensure_plate_free(db, changes["plate_number"], exclude_id=car_id)
    for field, value in changes.items():
        setattr(car, field, value)
    db.commit()
    audit.log("car.update", user, "car", car.id)
    return car


@router.delete("/{car_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_car(car_id: int, user: CurrentUser, db: DbSession, audit: Audit):
    car = _get_or_404(db, car_id, user)
    db.delete(car)
    db.commit()  # з історією записів авто не видалиться: поверне 409
    audit.log("car.delete", user, "car", car_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
