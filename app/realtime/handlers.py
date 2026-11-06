"""Обробники подій Socket.IO: підключення, кімнати, онлайн-статус, відновлення пропущеного.

Кожне з'єднання проходить автентифікацію за JWT-токеном у `auth.token`.
Подробиці протоколу — у docs/WEBSOCKET.md.
"""
import asyncio
import logging
import time
from collections import deque
from datetime import date

import anyio.to_thread
from socketio.exceptions import ConnectionRefusedError

from app.core import database
from app.core.config import settings
from app.core.errors import AppError
from app.core.observability import WS_CONNECTIONS
from app.core.security import decode_token
from app.models import User, UserRole
from app.realtime import events as event_store
from app.realtime import presence
from app.realtime.sio import sio

log = logging.getLogger("carwash.realtime")

MAX_SLOT_ROOMS = 10
_hits: dict[str, deque[float]] = {}


def _load_user(user_id: int) -> dict | None:
    # Окрема коротка сесія БД: хендлери Socket.IO живуть поза запитами FastAPI
    with database.SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            return None
        return {"id": user.id, "role": user.role.value, "name": user.full_name, "rooms": event_store.rooms_for(user)}


def _replay(rooms: list[str], since: int, limit: int | None):
    with database.SessionLocal() as db:
        return event_store.fetch_since(db, rooms, since, limit)


def _allow(sid: str) -> bool:
    """Обмеження частоти вхідних подій від одного з'єднання (ковзне вікно)."""
    now = time.monotonic()
    hits = _hits.setdefault(sid, deque())
    window = settings.ws_rate_limit_window_seconds
    while hits and hits[0] <= now - window:
        hits.popleft()
    if len(hits) >= settings.ws_rate_limit_events:
        return False
    hits.append(now)
    return True


async def _close_later(sid: str) -> None:
    await asyncio.sleep(0.2)
    await sio.disconnect(sid)


async def _guard(sid: str) -> dict:
    """Перевіряє, що токен ще чинний і ліміт не перевищено. Повертає сесію або словник помилки."""
    session = await sio.get_session(sid)
    if session["exp"] <= time.time():
        # Токен спливе під час відкритого з'єднання. Повідомляємо клієнта: він оновлює токен
        # через /api/auth/refresh і підключається знову з новим auth.token
        await sio.emit("auth:expired", {}, to=sid)
        # Відповідь на запит (ack) має встигнути піти клієнту, тому розриваємо з'єднання з невеликою затримкою
        sio.start_background_task(_close_later, sid)
        return {"error": {"ok": False, "code": "TOKEN_EXPIRED"}}
    if not _allow(sid):
        return {"error": {"ok": False, "code": "RATE_LIMITED"}}
    return session


@sio.event
async def connect(sid, environ, auth):
    token = auth.get("token") if isinstance(auth, dict) else None
    if not token:
        raise ConnectionRefusedError("unauthorized")
    try:
        payload = decode_token(token, "access")
    except AppError:
        raise ConnectionRefusedError("unauthorized") from None

    user = await anyio.to_thread.run_sync(_load_user, int(payload["sub"]))
    if user is None:
        raise ConnectionRefusedError("unauthorized")

    await sio.save_session(sid, {"user_id": user["id"], "role": user["role"], "exp": payload["exp"], "slots": []})
    for room in user["rooms"]:
        await sio.enter_room(sid, room)

    WS_CONNECTIONS.inc()
    if presence.add(user["id"], user["role"], user["name"], sid):
        await sio.emit(
            "presence:update",
            {"id": None, "data": {"user_id": user["id"], "role": user["role"], "online": True}},
            room=f"role:{UserRole.ADMIN.value}",
        )
    log.info("WS підключено: user=%s sid=%s", user["id"], sid)


@sio.event
async def disconnect(sid, reason=None):
    session = await sio.get_session(sid)
    _hits.pop(sid, None)
    WS_CONNECTIONS.dec()
    if presence.remove(session["user_id"], sid):
        await sio.emit(
            "presence:update",
            {"id": None, "data": {"user_id": session["user_id"], "role": session["role"], "online": False}},
            room=f"role:{UserRole.ADMIN.value}",
        )


@sio.on("events:since")
async def events_since(sid, data=None):
    """Відновлення після обриву: клієнт передає номер останньої отриманої події."""
    session = await _guard(sid)
    if "error" in session:
        return session["error"]
    try:
        last_id = int((data or {}).get("last_id", 0))
    except (TypeError, ValueError):
        return {"ok": False, "code": "BAD_REQUEST"}
    rooms = sio.rooms(sid)
    items, has_more = await anyio.to_thread.run_sync(_replay, rooms, last_id, None)
    return {"ok": True, "events": items, "has_more": has_more}


@sio.on("slots:subscribe")
async def slots_subscribe(sid, data=None):
    """Підписка на зміни вільних слотів за датою: клієнт, який дивиться календар, бачить зайняті слоти наживо."""
    session = await _guard(sid)
    if "error" in session:
        return session["error"]
    try:
        day = date.fromisoformat((data or {}).get("date", "")).isoformat()
    except ValueError:
        return {"ok": False, "code": "BAD_DATE"}
    if day not in session["slots"]:
        if len(session["slots"]) >= MAX_SLOT_ROOMS:
            return {"ok": False, "code": "TOO_MANY_SUBSCRIPTIONS"}
        session["slots"].append(day)
        await sio.save_session(sid, session)
        await sio.enter_room(sid, f"slots:{day}")
    return {"ok": True, "date": day}


@sio.on("slots:unsubscribe")
async def slots_unsubscribe(sid, data=None):
    session = await _guard(sid)
    if "error" in session:
        return session["error"]
    day = (data or {}).get("date", "")
    if day in session["slots"]:
        session["slots"].remove(day)
        await sio.save_session(sid, session)
        await sio.leave_room(sid, f"slots:{day}")
    return {"ok": True}


@sio.on("presence:list")
async def presence_list(sid, data=None):
    session = await _guard(sid)
    if "error" in session:
        return session["error"]
    if session["role"] != UserRole.ADMIN.value:
        return {"ok": False, "code": "FORBIDDEN"}
    return {"ok": True, "users": presence.snapshot()}
