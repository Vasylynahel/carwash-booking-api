"""Тести Socket.IO на справжньому сервері (uvicorn у фоновому потоці).

REST-запити тут теж ідуть на живий сервер (requests), щоб події розсилались у той самий
цикл подій, де працюють з'єднання. Дані, які не розсилають подій (реєстрація, користувачі),
готуються через звичайні фікстури.
"""
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import requests
import socketio
import uvicorn
from socketio.exceptions import ConnectionError as SioConnectionError

from app.core.config import settings
from app.main import application
from app.realtime.sio import sio
from tests.helpers import tomorrow_at

EVENTS = [
    "booking:created", "booking:updated", "booking:status", "booking:deleted",
    "slots:changed", "catalog:changed", "presence:update", "notification", "auth:expired",
]


@pytest.fixture(scope="module")
def server_url():
    # Один сервер на модуль: Socket.IO прив'язується до першого циклу подій, тому
    # перезапускати його на кожен тест не можна
    # Тестовий сервер стоїть на випадковому порту, якого немає в списку дозволених origin-ів,
    # тому на час тестів дозволяємо все; перевірка CORS має окремий тест нижче
    sio.eio.cors_allowed_origins = "*"
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


class Api:
    def __init__(self, base):
        self.base = base

    def __call__(self, method, path, headers=None, **kw):
        r = requests.request(method, self.base + path, headers=headers, timeout=10, **kw)
        return r


class Listener:
    """Підключений Socket.IO-клієнт, що запам'ятовує всі отримані події."""

    def __init__(self, url, token):
        self.url, self.token = url, token
        self.sio = socketio.Client(reconnection=False)
        self.got = defaultdict(list)
        for ev in EVENTS:
            self.sio.on(ev, lambda payload, ev=ev: self.got[ev].append(payload))

    def connect(self):
        self.sio.connect(self.url, auth={"token": self.token}, transports=["websocket"], wait_timeout=5)
        return self

    def call(self, event, data=None):
        return self.sio.call(event, data or {}, timeout=5)

    def wait(self, event, count=1, timeout=4):
        end = time.time() + timeout
        while len(self.got[event]) < count and time.time() < end:
            time.sleep(0.05)
        return self.got[event]

    def close(self):
        if self.sio.connected:
            self.sio.disconnect()


@pytest.fixture()
def api(server_url, client):  # client: підміняє БД на SQLite для цього тесту
    return Api(server_url)


@pytest.fixture()
def listeners(server_url):
    opened: list[Listener] = []

    def factory(token):
        listener = Listener(server_url, token).connect()
        opened.append(listener)
        return listener

    yield factory
    for listener in opened:
        listener.close()
    time.sleep(0.2)


def token_of(user):  # noqa: D103
    return user["headers"]["Authorization"].removeprefix("Bearer ")


def prepare(api, admin):
    """Каталог створюємо через живий сервер: ці дії розсилають catalog:changed."""
    h = admin["headers"]
    service = api("POST", "/api/services", h, json={"name": "Мийка", "category": "wash", "duration_minutes": 60, "price": "500"}).json()
    bay = api("POST", "/api/bays", h, json={"name": "Пост 1"}).json()
    return service, bay


def book(api, user, car_id, service_id, hour=10):
    return api(
        "POST", "/api/bookings", user["headers"],
        json={"car_id": car_id, "service_ids": [service_id], "scheduled_at": tomorrow_at(hour)},
    )


def test_connection_requires_valid_token(server_url, make_client_user):
    def refused(auth):
        errors = []
        c = socketio.Client(reconnection=False)
        c.on("connect_error", errors.append)  # саме сюди сервер надсилає причину відмови
        with pytest.raises(SioConnectionError):
            c.connect(server_url, auth=auth, transports=["websocket"], wait_timeout=5)
        return errors

    for auth in ({}, {"token": "garbage"}):
        assert "unauthorized" in str(refused(auth))

    # refresh-токен не підходить як токен доступу
    u = make_client_user()
    assert "unauthorized" in str(refused({"token": u["tokens"]["refresh_token"]}))


def test_origin_check(server_url, admin, monkeypatch):
    token = token_of(admin)

    def try_connect():
        c = socketio.Client(reconnection=False)
        c.connect(server_url, auth={"token": token}, transports=["websocket"], wait_timeout=5)
        return c

    # браузерний Origin цього клієнта (адреса сервера) не входить до дозволених: відмова
    monkeypatch.setattr(sio.eio, "cors_allowed_origins", [settings.frontend_url])
    with pytest.raises(SioConnectionError):
        try_connect()

    # а якщо Origin дозволено, з'єднання встановлюється
    monkeypatch.setattr(sio.eio, "cors_allowed_origins", [settings.frontend_url, server_url])
    ok = try_connect()
    assert ok.connected
    ok.disconnect()


def test_booking_events_go_to_the_right_rooms(api, admin, make_client_user, listeners):
    service, bay = prepare(api, admin)
    a, b = make_client_user("a@example.com"), make_client_user("b@example.com")
    car = api("POST", "/api/cars", a["headers"], json={"brand": "Skoda", "model": "Octavia", "plate_number": "AA1111AA"}).json()

    la, lb, ladmin = listeners(token_of(a)), listeners(token_of(b)), listeners(token_of(admin))
    day = tomorrow_at(10)[:10]
    watcher = listeners(token_of(b))
    assert watcher.call("slots:subscribe", {"date": day})["ok"] is True

    r = book(api, a, car["id"], service["id"])
    assert r.status_code == 201, r.text

    created = la.wait("booking:created")[0]
    assert created["data"]["id"] == r.json()["id"] and created["id"] is not None
    assert ladmin.wait("booking:created")             # адміністратор бачить усі записи
    assert watcher.wait("slots:changed")[0]["data"] == {"date": day}
    assert la.wait("notification")[0]["data"]["type"] == "booking_created"
    assert ladmin.wait("notification")[0]["data"]["priority"] == "low"
    time.sleep(0.3)
    assert lb.got["booking:created"] == []            # чужий клієнт нічого не отримав
    assert lb.got["notification"] == []

    api("PATCH", f"/api/bookings/{r.json()['id']}/status", admin["headers"], json={"status": "in_progress"})
    assert la.wait("booking:status")[0]["data"]["status"] == "in_progress"
    assert la.wait("notification", count=2)[1]["data"]["type"] == "booking_status"


def test_catalog_changes_reach_everyone(api, admin, make_client_user, listeners):
    u = make_client_user()
    l = listeners(token_of(u))
    api("POST", "/api/services", admin["headers"], json={"name": "Віск", "category": "addon", "duration_minutes": 20, "price": "100"})
    ev = l.wait("catalog:changed")[0]["data"]
    assert ev["entity"] == "service" and ev["action"] == "created"


def test_online_presence(api, admin, make_client_user, listeners):
    u = make_client_user()
    ladmin = listeners(token_of(admin))
    lu = listeners(token_of(u))

    # адміністратор отримує й власне підключення, і підключення клієнта
    upd = ladmin.wait("presence:update", count=2)
    assert {"user_id": u["user"]["id"], "role": "client", "online": True} in [e["data"] for e in upd]

    online = ladmin.call("presence:list")
    assert online["ok"] and {x["user_id"] for x in online["users"]} == {admin["user"]["id"], u["user"]["id"]}
    assert lu.call("presence:list") == {"ok": False, "code": "FORBIDDEN"}
    assert api("GET", "/api/presence", admin["headers"]).json()["users"]

    # друга вкладка того самого користувача не змінює статус; останнє закриття повертає офлайн
    second = listeners(token_of(u))
    time.sleep(0.3)
    assert len(ladmin.got["presence:update"]) == 2
    lu.close()
    time.sleep(0.3)
    assert len(ladmin.got["presence:update"]) == 2   # ще одна вкладка відкрита: клієнт усе ще онлайн
    second.close()
    assert ladmin.wait("presence:update", count=3)[-1]["data"] == {
        "user_id": u["user"]["id"], "role": "client", "online": False
    }


def test_missed_events_are_replayed_after_reconnect(api, admin, make_client_user, listeners):
    service, bay = prepare(api, admin)
    a = make_client_user("a@example.com")
    car = api("POST", "/api/cars", a["headers"], json={"brand": "Audi", "model": "A4", "plate_number": "AA2222AA"}).json()

    first = listeners(token_of(a))
    r1 = book(api, a, car["id"], service["id"], hour=10)
    last_seen = first.wait("booking:created")[0]["id"]
    first.close()                                      # «обрив»: клієнт офлайн

    r2 = book(api, a, car["id"], service["id"], hour=12)   # поки його немає, відбувається ще запис
    assert r2.status_code == 201
    api("PATCH", f"/api/bookings/{r2.json()['id']}/status", a["headers"], json={"status": "cancelled"})

    back = listeners(token_of(a))                      # повернувся
    result = back.call("events:since", {"last_id": last_seen})
    assert result["ok"] and result["has_more"] is False
    assert [e["type"] for e in result["events"]] == ["booking:created", "booking:status"]
    assert all(e["id"] > last_seen for e in result["events"])
    assert result["events"][0]["data"]["id"] == r2.json()["id"]

    # а тепер від початку: бачимо й перший запис
    full = back.call("events:since", {"last_id": 0})
    assert [e["data"]["id"] for e in full["events"]][0] == r1.json()["id"]
    assert back.call("events:since", {"last_id": "abc"}) == {"ok": False, "code": "BAD_REQUEST"}


def test_expired_token_closes_connection(admin, listeners):
    short = jwt.encode(
        {"sub": str(admin["user"]["id"]), "role": "admin", "type": "access",
         "exp": datetime.now(UTC) + timedelta(seconds=2)},
        settings.jwt_secret, algorithm="HS256",
    )
    l = listeners(short)
    assert l.call("presence:list")["ok"] is True
    time.sleep(2.5)
    assert l.call("presence:list") == {"ok": False, "code": "TOKEN_EXPIRED"}
    assert l.wait("auth:expired")
    time.sleep(0.3)
    assert l.sio.connected is False


def test_websocket_events_are_rate_limited(admin, listeners, monkeypatch):
    monkeypatch.setattr(settings, "ws_rate_limit_events", 3)
    l = listeners(token_of(admin))
    codes = [l.call("presence:list").get("code", "ok") for _ in range(5)]
    assert codes == ["ok", "ok", "ok", "RATE_LIMITED", "RATE_LIMITED"]


def test_slot_subscription_validation(admin, listeners):
    l = listeners(token_of(admin))
    assert l.call("slots:subscribe", {"date": "not-a-date"}) == {"ok": False, "code": "BAD_DATE"}
    for i in range(10):
        assert l.call("slots:subscribe", {"date": f"2030-01-{i + 1:02d}"})["ok"] is True
    assert l.call("slots:subscribe", {"date": "2030-02-01"}) == {"ok": False, "code": "TOO_MANY_SUBSCRIPTIONS"}
    assert l.call("slots:unsubscribe", {"date": "2030-01-01"})["ok"] is True
    assert l.call("slots:subscribe", {"date": "2030-02-01"})["ok"] is True
