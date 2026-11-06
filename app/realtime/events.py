"""Журнал подій: збереження, відновлення пропущених і очищення старих."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Event, User


def rooms_for(user: User) -> list[str]:
    """Кімнати, у яких користувач перебуває автоматично одразу після підключення."""
    return [f"user:{user.id}", f"role:{user.role.value}", "all"]


def store(db: Session, rooms: list[str], event_type: str, data: dict) -> list[tuple[str, int]]:
    rows = [Event(room=room, type=event_type, payload=data) for room in rooms]
    db.add_all(rows)
    db.commit()
    return [(r.room, r.id) for r in rows]


def serialize(e: Event) -> dict:
    return {
        "id": e.id,
        "type": e.type,
        "room": e.room,
        "data": e.payload,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def fetch_since(db: Session, rooms: list[str], since: int, limit: int | None = None) -> tuple[list[dict], bool]:
    """Події з номером більшим за `since` у кімнатах користувача, від старих до нових."""
    limit = min(limit or settings.replay_limit, settings.replay_limit)
    rows = db.scalars(
        select(Event).where(Event.room.in_(rooms), Event.id > since).order_by(Event.id).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return [serialize(r) for r in rows[:limit]], has_more


def cleanup(db: Session) -> int:
    """Видаляє події, старші за EVENTS_RETENTION_DAYS: пропущені давно події клієнту вже не потрібні."""
    cutoff = datetime.now(UTC) - timedelta(days=settings.events_retention_days)
    result = db.execute(delete(Event).where(Event.created_at < cutoff))
    db.commit()
    return result.rowcount or 0
