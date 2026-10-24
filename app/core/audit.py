from typing import Annotated

from fastapi import Depends, Request

from app.deps import DbSession
from app.models import AuditLog, User


class AuditWriter:
    """Записує дії користувачів у журнал. Створюється окремо на кожен запит."""

    def __init__(self, db, request: Request):
        self.db = db
        self.ip = request.client.host if request.client else None

    def log(
        self,
        action: str,
        actor: User | int | None = None,
        entity: str | None = None,
        entity_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        user_id = actor.id if isinstance(actor, User) else actor
        self.db.add(
            AuditLog(
                user_id=user_id, action=action, entity=entity, entity_id=entity_id,
                details=details, ip=self.ip,
            )
        )
        # Окремий commit: запис про невдалий вхід теж має зберегтись,
        # хоча основна дія в цьому запиті нічого не змінювала
        self.db.commit()


def get_audit(db: DbSession, request: Request) -> AuditWriter:
    return AuditWriter(db, request)


Audit = Annotated[AuditWriter, Depends(get_audit)]
