from app.core.config import settings
from tests.helpers import make_bay, make_car, make_service, tomorrow_at


def create_booking(client, user, car, service, hour):
    r = client.post(
        "/api/bookings", headers=user["headers"],
        json={"car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": tomorrow_at(hour)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_event_log_replay_by_rooms(client, admin, make_client_user, make_master):
    a = make_client_user("a@example.com")
    b = make_client_user("b@example.com")
    car_a, car_b = make_car(client, a["headers"], "AA1111AA"), make_car(client, b["headers"], "BB2222BB")
    service = make_service(client, admin["headers"])
    make_bay(client, admin["headers"])
    make_bay(client, admin["headers"], "Пост 2")

    first = create_booking(client, a, car_a, service, 10)
    create_booking(client, b, car_b, service, 10)

    mine = client.get("/api/events", headers=a["headers"]).json()
    assert [e["data"]["id"] for e in mine["events"]] == [first["id"]]
    assert mine["events"][0]["type"] == "booking:created" and mine["events"][0]["room"] == f"user:{a['user']['id']}"

    everything = client.get("/api/events", headers=admin["headers"]).json()
    assert len(everything["events"]) == 2  # адміністратор бачить усі записи через role:admin

    # відновлення: «я вже отримав до цієї події, що було далі?»
    last = mine["events"][-1]["id"]
    client.patch(
        f"/api/bookings/{first['id']}/status", headers=a["headers"], json={"status": "cancelled"}
    )
    after = client.get("/api/events", headers=a["headers"], params={"since": last}).json()
    assert [e["type"] for e in after["events"]] == ["booking:status"]
    assert after["events"][0]["data"]["status"] == "cancelled"

    assert client.get("/api/events", params={"since": 0}).status_code == 401


def test_replay_limit_and_has_more(client, admin, make_client_user):
    a = make_client_user("a@example.com")
    car = make_car(client, a["headers"])
    service = make_service(client, admin["headers"], minutes=30)
    make_bay(client, admin["headers"])
    for hour in (9, 10, 11):
        create_booking(client, a, car, service, hour)

    page = client.get("/api/events", headers=a["headers"], params={"limit": 2}).json()
    assert len(page["events"]) == 2 and page["has_more"] is True
    rest = client.get("/api/events", headers=a["headers"], params={"since": page["events"][-1]["id"]}).json()
    assert len(rest["events"]) == 1 and rest["has_more"] is False


def test_old_events_are_cleaned_up(client, admin, make_client_user):
    from datetime import UTC, datetime, timedelta

    from app.models import Event
    from app.realtime import events as event_store

    with client.Session() as db:
        db.add(Event(room="all", type="old", payload={}, created_at=datetime.now(UTC) - timedelta(days=settings.events_retention_days + 1)))
        db.add(Event(room="all", type="fresh", payload={}))
        db.commit()
        assert event_store.cleanup(db) == 1
        left = [e.type for e in db.query(Event).all()]
    assert left == ["fresh"]


def test_presence_endpoint_admin_only(client, admin, make_client_user):
    u = make_client_user()
    assert client.get("/api/presence", headers=u["headers"]).status_code == 403
    assert client.get("/api/presence", headers=admin["headers"]).json() == {"users": []}


def test_metrics_endpoint(client, monkeypatch):
    client.get("/health")
    r = client.get("/metrics")
    assert r.status_code == 200 and "http_requests_total" in r.text and 'path="/health"' in r.text
    monkeypatch.setattr(settings, "metrics_token", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200
