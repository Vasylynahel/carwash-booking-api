from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Service, ServiceCategory
from app.schemas.common import Page
from app.schemas.service import ServiceCreate, ServiceRead, ServiceUpdate

router = APIRouter(prefix="/services", tags=["Послуги"])


def _get_or_404(db, service_id: int) -> Service:
    service = db.get(Service, service_id)
    if service is None:
        raise NotFoundError("Послугу не знайдено")
    return service


def _ensure_name_free(db, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Service.id).where(Service.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Service.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise ConflictError("Послуга з такою назвою вже є в каталозі")


@router.post("", response_model=ServiceRead, status_code=status.HTTP_201_CREATED)
def create_service(data: ServiceCreate, db: DbSession):
    _ensure_name_free(db, data.name)
    service = Service(**data.model_dump())
    db.add(service)
    db.commit()
    return service


@router.get("", response_model=Page[ServiceRead])
def list_services(
    db: DbSession,
    pager: Pager,
    search: Annotated[str | None, Query(max_length=100)] = None,
    category: ServiceCategory | None = None,
    is_active: bool | None = None,
):
    stmt = select(Service).order_by(Service.category, Service.price, Service.id)
    if search:
        stmt = stmt.where(Service.name.ilike(f"%{search}%"))
    if category:
        stmt = stmt.where(Service.category == category)
    if is_active is not None:
        stmt = stmt.where(Service.is_active.is_(is_active))
    return paginate(db, stmt, pager)


@router.get("/{service_id}", response_model=ServiceRead)
def get_service(service_id: int, db: DbSession):
    return _get_or_404(db, service_id)


@router.patch("/{service_id}", response_model=ServiceRead)
def update_service(service_id: int, data: ServiceUpdate, db: DbSession):
    service = _get_or_404(db, service_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes:
        _ensure_name_free(db, changes["name"], exclude_id=service_id)
    for field, value in changes.items():
        setattr(service, field, value)
    db.commit()
    return service


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: int, db: DbSession):
    service = _get_or_404(db, service_id)
    db.delete(service)
    db.commit()  # послугу, що є в записах, не видалити: деактивуйте її через PATCH (is_active=false)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
