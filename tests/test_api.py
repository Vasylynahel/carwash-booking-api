from datetime import datetime, timedelta

from app.core.config import settings


def make_user(client, email="ivan@example.com", role="client", **extra):
    r = client.post(
        "/api/users",
        json={"email": email, "password": "password123", "full_name": "Іван Петренко", "role": role, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_car(client, owner_id, plate="AA1234BB"):
    r = client.post(
        "/api/cars", json={"owner_id": owner_id, "brand": "Skoda", "model": "Octavia", "plate_number": plate}
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_service(client, name="Комплексна мийка", minutes=60, price="500.00"):
    r = client.post(
        "/api/services",
        json={"name": name, "category": "wash", "duration_minutes": minutes, "price": price},
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_bay(client, name="Пост 1"):
    r = client.post("/api/bays", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def tomorrow_at(hour: int, minute: int = 0) -> str:
    day = (datetime.now(settings.tz) + timedelta(days=1)).date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz).isoformat()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_user_validation_and_no_hash_leak(client):
    bad = client.post("/api/users", json={"email": "not-an-email", "password": "123", "full_name": "A"})
    assert bad.status_code == 422
    assert {d["field"] for d in bad.json()["details"]} >= {"email", "password", "full_name"}

    user = make_user(client)
    assert "password" not in user and "password_hash" not in user

    dup = client.post(
        "/api/users", json={"email": "IVAN@example.com", "password": "password123", "full_name": "Інший"}
    )
    assert dup.status_code == 409


def test_crud_service_and_pagination(client):
    for i in range(3):
        make_service(client, name=f"Послуга {i}")
    page = client.get("/api/services", params={"page": 1, "limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["pages"] == 2

    s = page["items"][0]
    patched = client.patch(f"/api/services/{s['id']}", json={"price": "999.50"}).json()
    assert patched["price"] == "999.50"

    assert client.get("/api/services/9999").status_code == 404
    assert client.delete(f"/api/services/{s['id']}").status_code == 204


def test_car_plate_normalized_and_unique(client):
    owner = make_user(client)
    car = make_car(client, owner["id"], plate="aa 1234 bb")
    assert car["plate_number"] == "AA1234BB"
    dup = client.post(
        "/api/cars",
        json={"owner_id": owner["id"], "brand": "Audi", "model": "A4", "plate_number": "AA1234BB"},
    )
    assert dup.status_code == 409


def setup_booking_env(client):
    client_user = make_user(client)
    car = make_car(client, client_user["id"])
    service = make_service(client)
    bay = make_bay(client)
    return client_user, car, service, bay


def test_booking_flow_and_conflicts(client):
    user, car, service, bay = setup_booking_env(client)
    payload = {
        "client_id": user["id"],
        "car_id": car["id"],
        "service_ids": [service["id"]],
        "scheduled_at": tomorrow_at(10),
    }
    r = client.post("/api/bookings", json=payload)
    assert r.status_code == 201, r.text
    booking = r.json()
    assert booking["bay_id"] == bay["id"] and booking["total_price"] == "500.00"

    # той самий час: єдиний пост зайнятий
    other_user = make_user(client, email="olena@example.com")
    other_car = make_car(client, other_user["id"], plate="BB4321CC")
    clash = client.post("/api/bookings", json={**payload, "client_id": other_user["id"], "car_id": other_car["id"]})
    assert clash.status_code == 409

    # впритул після кінця першого запису (11:00) — вільно
    ok = client.post(
        "/api/bookings",
        json={**payload, "client_id": other_user["id"], "car_id": other_car["id"], "scheduled_at": tomorrow_at(11)},
    )
    assert ok.status_code == 201

    # чужий автомобіль
    foreign = client.post("/api/bookings", json={**payload, "car_id": other_car["id"], "scheduled_at": tomorrow_at(15)})
    assert foreign.status_code == 422


def test_booking_rules(client):
    user, car, service, bay = setup_booking_env(client)
    base = {"client_id": user["id"], "car_id": car["id"], "service_ids": [service["id"]]}

    outside = client.post("/api/bookings", json={**base, "scheduled_at": tomorrow_at(6)})
    assert outside.status_code == 422

    naive = client.post("/api/bookings", json={**base, "scheduled_at": "2030-01-01T10:00:00"})
    assert naive.status_code == 422  # без часового поясу

    past = client.post("/api/bookings", json={**base, "scheduled_at": "2020-01-01T10:00:00+02:00"})
    assert past.status_code == 422

    missing = client.post("/api/bookings", json={**base, "service_ids": [999], "scheduled_at": tomorrow_at(10)})
    assert missing.status_code == 404


def test_status_transitions_and_delete(client):
    user, car, service, bay = setup_booking_env(client)
    b = client.post(
        "/api/bookings",
        json={"client_id": user["id"], "car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": tomorrow_at(10)},
    ).json()

    assert client.patch(f"/api/bookings/{b['id']}/status", json={"status": "done"}).status_code == 409
    assert client.delete(f"/api/bookings/{b['id']}").status_code == 409
    assert client.patch(f"/api/bookings/{b['id']}/status", json={"status": "in_progress"}).status_code == 200
    assert client.patch(f"/api/bookings/{b['id']}/status", json={"status": "cancelled"}).status_code == 200
    assert client.delete(f"/api/bookings/{b['id']}").status_code == 204


def test_assign_master_and_filter(client):
    user, car, service, bay = setup_booking_env(client)
    master = make_user(client, email="master@example.com", role="master")
    b = client.post(
        "/api/bookings",
        json={"client_id": user["id"], "car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": tomorrow_at(10)},
    ).json()
    r = client.patch(f"/api/bookings/{b['id']}", json={"master_id": master["id"]})
    assert r.status_code == 200 and r.json()["master_id"] == master["id"]

    by_client = client.get("/api/bookings", params={"client_id": user["id"], "status": "planned"}).json()
    assert by_client["total"] == 1
    not_master = client.patch(f"/api/bookings/{b['id']}", json={"master_id": user["id"]})
    assert not_master.status_code == 422


def test_availability(client):
    user, car, service, bay = setup_booking_env(client)
    day = (datetime.now(settings.tz) + timedelta(days=1)).date().isoformat()
    r = client.get("/api/bookings/availability", params={"date": day, "service_ids": [service["id"]]})
    assert r.status_code == 200
    slots = r.json()
    assert slots[0]["start"].startswith(f"{day}T09:00")
    assert slots[-1]["end"].startswith(f"{day}T20:00")

    client.post(
        "/api/bookings",
        json={"client_id": user["id"], "car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": tomorrow_at(10)},
    )
    after = client.get("/api/bookings/availability", params={"date": day, "service_ids": [service["id"]]}).json()
    starts = {s["start"][11:16] for s in after}
    assert "10:00" not in starts and "10:30" not in starts and "09:00" in starts and "11:00" in starts
