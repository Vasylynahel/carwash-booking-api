"""Тести лабораторної 1 (CRUD і логіка запису), адаптовані під автентифікацію з лабораторної 2."""
from datetime import datetime, timedelta

from tests.helpers import make_bay, make_car, make_service, tomorrow_at


def book(client, headers, car_id, service_ids, when, **extra):
    return client.post(
        "/api/bookings", headers=headers,
        json={"car_id": car_id, "service_ids": service_ids, "scheduled_at": when, **extra},
    )


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_admin_creates_users_validation(client, admin):
    bad = client.post(
        "/api/users", headers=admin["headers"],
        json={"email": "not-an-email", "password": "123", "full_name": "A"},
    )
    assert bad.status_code == 422
    ok = client.post(
        "/api/users", headers=admin["headers"],
        json={"email": "m@example.com", "password": "password123", "full_name": "Майстер", "role": "master"},
    )
    assert ok.status_code == 201 and ok.json()["role"] == "master"
    dup = client.post(
        "/api/users", headers=admin["headers"],
        json={"email": "M@example.com", "password": "password123", "full_name": "Інший"},
    )
    assert dup.status_code == 409


def test_crud_service_and_pagination(client, admin):
    for i in range(3):
        make_service(client, admin["headers"], name=f"Послуга {i}")
    page = client.get("/api/services", params={"page": 1, "limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["pages"] == 2

    s = page["items"][0]
    patched = client.patch(f"/api/services/{s['id']}", headers=admin["headers"], json={"price": "999.50"}).json()
    assert patched["price"] == "999.50"

    assert client.get("/api/services/9999").status_code == 404
    assert client.delete(f"/api/services/{s['id']}", headers=admin["headers"]).status_code == 204
    found = client.get("/api/services", params={"search": "Послуга 1"}).json()
    assert found["total"] == 1


def test_car_plate_normalized_and_unique(client, make_client_user):
    u = make_client_user()
    car = make_car(client, u["headers"], plate="aa 1234 bb")
    assert car["plate_number"] == "AA1234BB"
    dup = client.post(
        "/api/cars", headers=u["headers"],
        json={"brand": "Audi", "model": "A4", "plate_number": "AA1234BB"},
    )
    assert dup.status_code == 409


def env(client, admin, make_client_user, email="ivan@example.com", plate="AA1234BB", bays=1):
    user = make_client_user(email)
    car = make_car(client, user["headers"], plate)
    service = make_service(client, admin["headers"]) if not client.get("/api/services").json()["total"] else \
        client.get("/api/services").json()["items"][0]
    for i in range(bays):
        if not client.get("/api/bays", headers=admin["headers"]).json()["total"] > i:
            make_bay(client, admin["headers"], f"Пост {i + 1}")
    return user, car, service


def test_booking_flow_and_conflicts(client, admin, make_client_user):
    u1, car1, service = env(client, admin, make_client_user)
    u2, car2, _ = env(client, admin, make_client_user, "olena@example.com", "BB4321CC")

    r = book(client, u1["headers"], car1["id"], [service["id"]], tomorrow_at(10))
    assert r.status_code == 201, r.text
    booking = r.json()
    assert booking["total_price"] == "500.00" and booking["discount_percent"] == "0.00"

    # той самий час: єдиний пост зайнятий
    assert book(client, u2["headers"], car2["id"], [service["id"]], tomorrow_at(10)).status_code == 409
    # впритул після кінця першого запису (11:00) вільно
    assert book(client, u2["headers"], car2["id"], [service["id"]], tomorrow_at(11)).status_code == 201
    # чужий автомобіль
    assert book(client, u1["headers"], car2["id"], [service["id"]], tomorrow_at(15)).status_code == 422


def test_auto_bay_assignment_with_two_bays(client, admin, make_client_user):
    u1, car1, service = env(client, admin, make_client_user, bays=2)
    u2, car2, _ = env(client, admin, make_client_user, "olena@example.com", "BB4321CC", bays=2)
    first = book(client, u1["headers"], car1["id"], [service["id"]], tomorrow_at(10)).json()
    second = book(client, u2["headers"], car2["id"], [service["id"]], tomorrow_at(10))
    assert second.status_code == 201 and second.json()["bay_id"] != first["bay_id"]


def test_multiple_services_sum(client, admin, make_client_user):
    u, car, s1 = env(client, admin, make_client_user)
    s2 = make_service(client, admin["headers"], "Воскування", minutes=30, price="200.00")
    r = book(client, u["headers"], car["id"], [s1["id"], s2["id"]], tomorrow_at(10)).json()
    assert r["total_price"] == "700.00"
    # тривалості додаються: 60 + 30 хвилин
    assert datetime.fromisoformat(r["ends_at"]) - datetime.fromisoformat(r["scheduled_at"]) == timedelta(minutes=90)
    dup = book(client, u["headers"], car["id"], [s1["id"], s1["id"]], tomorrow_at(15))
    assert dup.status_code == 422


def test_booking_rules(client, admin, make_client_user):
    u, car, service = env(client, admin, make_client_user)
    sid = [service["id"]]
    assert book(client, u["headers"], car["id"], sid, tomorrow_at(6)).status_code == 422       # до відкриття
    assert book(client, u["headers"], car["id"], sid, "2030-01-01T10:00:00").status_code == 422  # без пояса
    assert book(client, u["headers"], car["id"], sid, "2020-01-01T10:00:00+02:00").status_code == 422  # минуле
    assert book(client, u["headers"], car["id"], [999], tomorrow_at(10)).status_code == 404


def test_status_transitions_and_delete(client, admin, make_client_user):
    u, car, service = env(client, admin, make_client_user)
    b = book(client, u["headers"], car["id"], [service["id"]], tomorrow_at(10)).json()
    url = f"/api/bookings/{b['id']}/status"
    h = admin["headers"]

    assert client.patch(url, headers=h, json={"status": "done"}).status_code == 409
    assert client.delete(f"/api/bookings/{b['id']}", headers=h).status_code == 409
    assert client.patch(url, headers=h, json={"status": "in_progress"}).status_code == 200
    assert client.patch(url, headers=h, json={"status": "cancelled"}).status_code == 200
    assert client.delete(f"/api/bookings/{b['id']}", headers=h).status_code == 204


def test_assign_master_rules(client, admin, make_client_user, make_master):
    u, car, service = env(client, admin, make_client_user)
    master = make_master()
    b = book(client, u["headers"], car["id"], [service["id"]], tomorrow_at(10)).json()

    ok = client.patch(f"/api/bookings/{b['id']}", headers=admin["headers"], json={"master_id": master["user"]["id"]})
    assert ok.status_code == 200 and ok.json()["master_id"] == master["user"]["id"]
    not_master = client.patch(f"/api/bookings/{b['id']}", headers=admin["headers"], json={"master_id": u["user"]["id"]})
    assert not_master.status_code == 422


def test_booking_filters(client, admin, make_client_user):
    u, car, service = env(client, admin, make_client_user)
    book(client, u["headers"], car["id"], [service["id"]], tomorrow_at(10))
    by_client = client.get(
        "/api/bookings", headers=admin["headers"],
        params={"client_id": u["user"]["id"], "status": "planned"},
    ).json()
    assert by_client["total"] == 1
    assert client.get("/api/bookings", headers=admin["headers"], params={"status": "done"}).json()["total"] == 0


def test_availability_public(client, admin, make_client_user):
    from app.core.config import settings

    u, car, service = env(client, admin, make_client_user)
    day = (datetime.now(settings.tz) + timedelta(days=1)).date().isoformat()
    params = {"date": day, "service_ids": [service["id"]]}

    slots = client.get("/api/bookings/availability", params=params).json()  # без токена
    assert slots[0]["start"].startswith(f"{day}T09:00") and slots[-1]["end"].startswith(f"{day}T20:00")
    assert slots[0]["price"] == "500.00" and slots[0]["discount_percent"] == "0.00"

    book(client, u["headers"], car["id"], [service["id"]], tomorrow_at(10))
    after = client.get("/api/bookings/availability", params=params).json()
    starts = {s["start"][11:16] for s in after}
    assert "10:00" not in starts and "10:30" not in starts and "09:00" in starts and "11:00" in starts
