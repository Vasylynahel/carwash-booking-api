from fastapi import APIRouter, Query
from typing import Annotated

from app.core.auth import AdminUser, CurrentUser
from app.deps import DbSession
from app.realtime import events as event_store
from app.realtime import presence

router = APIRouter(tags=["Реальний час"])


@router.get("/presence", summary="Хто зараз онлайн (адміністратор)")
def online_users(admin: AdminUser):
    return {"users": presence.snapshot()}


@router.get("/events", summary="Пропущені події (запасний спосіб до WebSocket)")
def missed_events(
    user: CurrentUser,
    db: DbSession,
    since: Annotated[int, Query(ge=0, description="Номер останньої отриманої події")] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Те саме, що подія `events:since`, але звичайним HTTP-запитом: зручно для перевірки й клієнтів без WebSocket."""
    items, has_more = event_store.fetch_since(db, event_store.rooms_for(user), since, limit)
    return {"events": items, "has_more": has_more}
