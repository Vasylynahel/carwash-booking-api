from tests.helpers import make_bay, make_car, make_service, tomorrow_at


def book(client, headers, car_id, service_id, when, **extra):
    return client.post(
        "/api/bookings", headers=headers,
        json={"car_id": car_id, "service_ids": [service_id], "scheduled_at": when, **extra},
    )


def test_catalog_public_but_changes_admin_only(client, admin, make_client_user):
    user = make_client_user()
    s = make_service(client, admin["headers"])
    assert client.get("/api/services").status_code == 200  # без токена
    assert client.get(f"/api/services/{s['id']}").status_code == 200

    payload = {"name": "Нова", "category": "wash", "duration_minutes": 30, "price": "100"}
    assert client.post("/api/services", json=payload).status_code == 401
    assert client.post("/api/services", headers=user["headers"], json=payload).status_code == 403
    assert client.patch(f"/api/services/{s['id']}", headers=user["headers"], json={"price": "1"}).status_code == 403
    assert client.delete(f"/api/services/{s['id']}", headers=user["headers"]).status_code == 403


def test_users_endpoints_roles(client, admin, make_client_user):
    a = make_client_user("a@example.com")
    b = make_client_user("b@example.com")

    assert client.get("/api/users", headers=a["headers"]).status_code == 403
    assert client.get("/api/users", headers=admin["headers"]).status_code == 200
    assert client.get(f"/api/users/{a['user']['id']}", headers=a["headers"]).status_code == 200
    assert client.get(f"/api/users/{b['user']['id']}", headers=a["headers"]).status_code == 403

    own = client.patch(f"/api/users/{a['user']['id']}", headers=a["headers"], json={"phone": "+380501234567"})
    assert own.status_code == 200
    # підвищити собі роль не вийде
    esc = client.patch(f"/api/users/{a['user']['id']}", headers=a["headers"], json={"role": "admin"})
    assert esc.status_code == 403
    assert client.delete(f"/api/users/{b['user']['id']}", headers=a["headers"]).status_code == 403
    assert client.delete(f"/api/users/{admin['user']['id']}", headers=admin["headers"]).status_code == 422


def test_clients_see_only_own_cars(client, admin, make_client_user):
    a = make_client_user("a@example.com")
    b = make_client_user("b@example.com")
    car_a = make_car(client, a["headers"], "AA1111AA")
    assert car_a["owner_id"] == a["user"]["id"]
    # чужий owner_id клієнт підмінити не може
    spoof = make_car(client, b["headers"], "BB2222BB", owner_id=a["user"]["id"])
    assert spoof["owner_id"] == b["user"]["id"]

    assert client.get(f"/api/cars/{car_a['id']}", headers=b["headers"]).status_code == 403
    assert client.patch(f"/api/cars/{car_a['id']}", headers=b["headers"], json={"brand": "X"}).status_code == 403
    assert client.get("/api/cars", headers=a["headers"]).json()["total"] == 1
    assert client.get("/api/cars", headers=admin["headers"]).json()["total"] == 2

    no_owner = client.post(
        "/api/cars", headers=admin["headers"],
        json={"brand": "Audi", "model": "A4", "plate_number": "CC3333CC"},
    )
    assert no_owner.status_code == 422


def test_booking_visibility_and_status_rights(client, admin, make_client_user, make_master):
    a = make_client_user("a@example.com")
    b = make_client_user("b@example.com")
    master = make_master()
    other_master = make_master("m2@example.com")
    make_bay(client, admin["headers"], "Пост 1")
    make_bay(client, admin["headers"], "Пост 2")
    s = make_service(client, admin["headers"])
    car_a = make_car(client, a["headers"], "AA1111AA")

    # клієнт не може записати чужим іменем, майстер не створює записи
    forged = book(client, a["headers"], car_a["id"], s["id"], tomorrow_at(10), client_id=b["user"]["id"])
    assert forged.status_code == 403
    assert book(client, master["headers"], car_a["id"], s["id"], tomorrow_at(10)).status_code == 403

    created = book(client, a["headers"], car_a["id"], s["id"], tomorrow_at(10))
    assert created.status_code == 201
    bid = created.json()["id"]
    assert created.json()["client_id"] == a["user"]["id"]

    # видимість
    assert client.get(f"/api/bookings/{bid}", headers=a["headers"]).status_code == 200
    assert client.get(f"/api/bookings/{bid}", headers=b["headers"]).status_code == 403
    assert client.get("/api/bookings", headers=b["headers"]).json()["total"] == 0
    assert client.get("/api/bookings", headers=a["headers"]).json()["total"] == 1

    # адмін призначає майстра: тепер той бачить запис, інший майстер — ні
    assert client.patch(f"/api/bookings/{bid}", headers=a["headers"], json={"master_id": master["user"]["id"]}).status_code == 403
    assert client.patch(f"/api/bookings/{bid}", headers=admin["headers"], json={"master_id": master["user"]["id"]}).status_code == 200
    assert client.get("/api/bookings", headers=master["headers"]).json()["total"] == 1
    assert client.get("/api/bookings", headers=other_master["headers"]).json()["total"] == 0
    assert client.get(f"/api/bookings/{bid}", headers=other_master["headers"]).status_code == 403

    # права на статуси
    url = f"/api/bookings/{bid}/status"
    assert client.patch(url, headers=a["headers"], json={"status": "in_progress"}).status_code == 403
    assert client.patch(url, headers=other_master["headers"], json={"status": "in_progress"}).status_code == 403
    assert client.patch(url, headers=master["headers"], json={"status": "cancelled"}).status_code == 403
    assert client.patch(url, headers=master["headers"], json={"status": "in_progress"}).status_code == 200
    assert client.patch(url, headers=master["headers"], json={"status": "done"}).status_code == 200

    # клієнт скасовує лише власний запис
    second = book(client, a["headers"], car_a["id"], s["id"], tomorrow_at(14)).json()
    assert client.patch(f"/api/bookings/{second['id']}/status", headers=b["headers"], json={"status": "cancelled"}).status_code == 403
    assert client.patch(f"/api/bookings/{second['id']}/status", headers=a["headers"], json={"status": "cancelled"}).status_code == 200


def test_audit_log_is_admin_only_and_records_actions(client, admin, make_client_user):
    u = make_client_user()
    client.post("/api/auth/login", json={"email": "ivan@example.com", "password": "wrong-pass1"})
    assert client.get("/api/audit-logs", headers=u["headers"]).status_code == 403

    logs = client.get("/api/audit-logs", headers=admin["headers"], params={"limit": 50}).json()
    actions = [i["action"] for i in logs["items"]]
    assert "auth.register" in actions and "auth.login_failed" in actions
    filtered = client.get("/api/audit-logs", headers=admin["headers"], params={"action": "auth.login"}).json()
    assert all(i["action"].startswith("auth.login") for i in filtered["items"])
