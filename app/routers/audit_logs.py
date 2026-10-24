from datetime import datetime

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter
from sqlalchemy import select

from app.core.auth import AdminUser
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import AuditLog
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["Журнал дій"])


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    entity: str | None
    entity_id: int | None
    details: dict | None
    ip: str | None
    created_at: datetime


@router.get("", response_model=Page[AuditLogRead], summary="Журнал дій (лише адміністратор)")
def list_audit_logs(
    admin: AdminUser,
    db: DbSession,
    pager: Pager,
    user_id: int | None = None,
    action: str | None = None,
    entity: str | None = None,
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    return paginate(db, stmt, pager)
