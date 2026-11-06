from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select, update

from app.core.auth import CurrentUser
from app.core.errors import NotFoundError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Notification, NotificationPriority
from app.schemas.common import Page

router = APIRouter(prefix="/notifications", tags=["Сповіщення"])


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    priority: NotificationPriority
    message: str
    booking_id: int | None
    is_read: bool
    created_at: datetime


def _own_or_404(db, user, notification_id: int) -> Notification:
    n = db.get(Notification, notification_id)
    # Чужі сповіщення «не існують» для користувача: 404, а не 403, щоб не підказувати чужі id
    if n is None or n.user_id != user.id:
        raise NotFoundError("Сповіщення не знайдено")
    return n


@router.get("", response_model=Page[NotificationRead], summary="Мої сповіщення")
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    pager: Pager,
    is_read: bool | None = None,
    type_: Annotated[str | None, Query(alias="type", max_length=30)] = None,
    priority: NotificationPriority | None = None,
):
    stmt = select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc())
    if is_read is not None:
        stmt = stmt.where(Notification.is_read.is_(is_read))
    if type_:
        stmt = stmt.where(Notification.type == type_)
    if priority:
        stmt = stmt.where(Notification.priority == priority)
    return paginate(db, stmt, pager)


# Маршрути без параметра шляху стоять вище за /{notification_id}
@router.get("/unread-count", summary="Кількість непрочитаних")
def unread_count(user: CurrentUser, db: DbSession):
    count = db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    )
    return {"count": count or 0}


@router.post("/read-all", summary="Позначити всі прочитаними")
def read_all(user: CurrentUser, db: DbSession):
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        .values(is_read=True)
    )
    db.commit()
    return {"updated": result.rowcount or 0}


@router.patch("/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, user: CurrentUser, db: DbSession):
    n = _own_or_404(db, user, notification_id)
    n.is_read = True
    db.commit()
    return n


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notification_id: int, user: CurrentUser, db: DbSession):
    n = _own_or_404(db, user, notification_id)
    db.execute(delete(Notification).where(Notification.id == n.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
