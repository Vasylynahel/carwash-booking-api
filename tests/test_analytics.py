from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models import Booking, BookingStatus
from tests.helpers import at, day_with_weekday, make_bay, make_car, make_service


@pytest.fixture()
def history(client, admin, make_client_user, monkeypatch):
    """13 минулих днів: щодня з 9:00 до 12:00 пост зайнятий, а з 12:00 до 20:00 порожній."""
    monkeypatch.setattr(settings, "auto_pricing_min_bookings", 10)
    user = make_client_user()
    car = make_car(client, user["headers"])
    service = make_service(client, admin["headers"])
    bay = make_bay(client, admin["headers"])

    today = datetime.now(settings.tz).date()
    with client.Session() as db:
        for days_ago in range(1, 14):
            d = today - timedelta(days=days_ago)
            start = datetime(d.year, d.month, d.day, 9, tzinfo=settings.tz).astimezone(UTC)
            db.add(
                Booking(
                    client_id=user["user"]["id"], car_id=car["id"], bay_id=bay["id"],
                    scheduled_at=start, ends_at=start + timedelta(hours=3),
                    status=BookingStatus.DONE, total_price=Decimal("500"),
                )
            )
        db.commit()
    return {"user": user, "service": service}


def test_analytics_admin_only(client, make_client_user):
    u = make_client_user()
    for path in ("occupancy", "quiet-hours"):
        assert client.get(f"/api/analytics/{path}", headers=u["headers"]).status_code == 403
    assert client.post("/api/analytics/quiet-hours/apply", headers=u["headers"]).status_code == 403
    assert client.get("/api/analytics/occupancy").status_code == 401


def test_not_enough_data_means_no_suggestions(client, admin, monkeypatch):
    make_bay(client, admin["headers"])
    r = client.get("/api/analytics/quiet-hours", headers=admin["headers"]).json()
    assert r["enough_data"] is False and r["suggestions"] == []

    applied = client.post("/api/analytics/quiet-hours/apply", headers=admin["headers"]).json()
    assert applied["applied"] is False
    assert client.get("/api/pricing-rules", headers=admin["headers"]).json()["total"] == 0


def test_occupancy_heatmap(client, admin, history):
    occ = client.get("/api/analytics/occupancy", headers=admin["headers"], params={"weeks": 2}).json()
    assert occ["enough_data"] is True and occ["bookings"] == 13 and occ["bays"] == 1
    assert len(occ["cells"]) == 7 * (settings.work_day_end - settings.work_day_start)
    load = {(c["weekday"], c["hour"]): c["load"] for c in occ["cells"]}
    assert all(load[(wd, 10)] >= 0.5 for wd in range(7))   # ранок зайнятий
    assert all(load[(wd, 15)] == 0 for wd in range(7))     # після обіду порожньо


def test_quiet_hours_suggestions(client, admin, history):
    r = client.get("/api/analytics/quiet-hours", headers=admin["headers"], params={"weeks": 2}).json()
    assert r["enough_data"] is True
    assert len(r["suggestions"]) == 7  # по одному блоку на кожен день тижня
    monday = next(s for s in r["suggestions"] if s["weekday"] == 0)
    assert (monday["start_hour"], monday["end_hour"], monday["discount_percent"]) == (12, 20, 15)
    assert all(s["start_hour"] >= 12 for s in r["suggestions"])  # зайняті ранкові години без знижки


def test_apply_creates_auto_rules_used_in_slots(client, admin, history):
    service = history["service"]
    r = client.post("/api/analytics/quiet-hours/apply", headers=admin["headers"], params={"weeks": 2}).json()
    assert r["applied"] is True and len(r["rules"]) == 7

    rules = client.get("/api/pricing-rules", headers=admin["headers"], params={"is_auto": "true", "limit": 50}).json()
    assert rules["total"] == 7 and all(x["is_auto"] for x in rules["items"])

    wed = day_with_weekday(2)
    slots = {
        s["start"][11:16]: s
        for s in client.get(
            "/api/bookings/availability", params={"date": wed.isoformat(), "service_ids": [service["id"]]}
        ).json()
    }
    assert slots["13:00"]["discount_percent"] == "15.00" and slots["13:00"]["price"] == "425.00"
    assert slots["13:00"]["rule_name"].startswith("Авто:")
    assert slots["09:30"]["discount_percent"] == "0.00"

    # повторне застосування замінює автоматичні правила, а не дублює
    client.post("/api/analytics/quiet-hours/apply", headers=admin["headers"], params={"weeks": 2})
    assert client.get("/api/pricing-rules", headers=admin["headers"], params={"is_auto": "true"}).json()["total"] == 7


def test_manual_rule_overrides_auto(client, admin, history):
    service = history["service"]
    client.post("/api/analytics/quiet-hours/apply", headers=admin["headers"], params={"weeks": 2})
    # адміністратор вирішив, що в середу 13:00–17:00 знижка лише 5%
    client.post(
        "/api/pricing-rules", headers=admin["headers"],
        json={"name": "Середа вручну", "weekday": 2, "start_time": "13:00:00", "end_time": "17:00:00", "discount_percent": "5"},
    )
    wed = day_with_weekday(2)
    slots = {
        s["start"][11:16]: s
        for s in client.get(
            "/api/bookings/availability", params={"date": wed.isoformat(), "service_ids": [service["id"]]}
        ).json()
    }
    assert slots["14:00"]["discount_percent"] == "5.00" and slots["14:00"]["rule_name"] == "Середа вручну"
    assert slots["18:00"]["discount_percent"] == "15.00"  # поза ручним правилом діє автоматичне


def test_booking_gets_auto_discount(client, admin, history):
    user, service = history["user"], history["service"]
    client.post("/api/analytics/quiet-hours/apply", headers=admin["headers"], params={"weeks": 2})
    car = client.get("/api/cars", headers=user["headers"]).json()["items"][0]
    r = client.post(
        "/api/bookings", headers=user["headers"],
        json={"car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": at(day_with_weekday(3), 14)},
    )
    assert r.status_code == 201
    assert r.json()["discount_percent"] == "15.00" and r.json()["total_price"] == "425.00"


def test_discount_formula():
    from app.services.analytics_service import discount_for_load

    assert discount_for_load(0.0) == 15
    assert discount_for_load(0.10) == 10      # 15 * (1 - 0.1/0.3) = 10
    assert discount_for_load(0.2) == 5        # 15 * (1 - 0.2/0.3) = 5
    assert discount_for_load(0.29) == 0       # менше кроку: знижки немає
    assert discount_for_load(0.30) == 0 and discount_for_load(0.9) == 0
