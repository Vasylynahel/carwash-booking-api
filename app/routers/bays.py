from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.core.audit import Audit
from app.core.auth import AdminUser, StaffUser
from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Bay
from app.schemas.bay import BayCreate, BayRead, BayUpdate
from app.schemas.common import Page

router = APIRouter(prefix="/bays", tags=["Пости"])


def _get_or_404(db, bay_id: int) -> Bay:
    bay = db.get(Bay, bay_id)
    if bay is None:
        raise NotFoundError("Пост не знайдено")
    return bay


def _ensure_name_free(db, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Bay.id).where(Bay.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Bay.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise ConflictError("Пост із такою назвою вже існує")


@router.post("", response_model=BayRead, status_code=status.HTTP_201_CREATED)
def create_bay(data: BayCreate, admin: AdminUser, db: DbSession, audit: Audit):
    _ensure_name_free(db, data.name)
    bay = Bay(**data.model_dump())
    db.add(bay)
    db.commit()
    audit.log("bay.create", admin, "bay", bay.id)
    return bay


@router.get("", response_model=Page[BayRead])
def list_bays(staff: StaffUser, db: DbSession, pager: Pager, is_active: bool | None = None):
    stmt = select(Bay).order_by(Bay.id)
    if is_active is not None:
        stmt = stmt.where(Bay.is_active.is_(is_active))
    return paginate(db, stmt, pager)


@router.get("/{bay_id}", response_model=BayRead)
def get_bay(bay_id: int, staff: StaffUser, db: DbSession):
    return _get_or_404(db, bay_id)


@router.patch("/{bay_id}", response_model=BayRead)
def update_bay(bay_id: int, data: BayUpdate, admin: AdminUser, db: DbSession, audit: Audit):
    bay = _get_or_404(db, bay_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes:
        _ensure_name_free(db, changes["name"], exclude_id=bay_id)
    for field, value in changes.items():
        setattr(bay, field, value)
    db.commit()
    audit.log("bay.update", admin, "bay", bay.id, {"fields": sorted(changes)})
    return bay


@router.delete("/{bay_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bay(bay_id: int, admin: AdminUser, db: DbSession, audit: Audit):
    bay = _get_or_404(db, bay_id)
    db.delete(bay)
    db.commit()  # пост, на якому були записи, не видалити: деактивуйте його
    audit.log("bay.delete", admin, "bay", bay_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
