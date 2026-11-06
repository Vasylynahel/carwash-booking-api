from tests.helpers import make_bay, make_car, make_service, tomorrow_at


def setup_booking(client, admin, make_client_user):
    user = make_client_user()
    car = make_car(client, user["headers"])
    service = make_service(client, admin["headers"])
    make_bay(client, admin["headers"])
    r = client.post(
        "/api/bookings", headers=user["headers"],
        json={"car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": tomorrow_at(10)},
    )
    assert r.status_code == 201, r.text
    return user, r.json()


def items(client, headers, **params):
    return client.get("/api/notifications", headers=headers, params=params).json()


def test_booking_creates_notifications_for_client_and_admin(client, admin, make_client_user):
    user, booking = setup_booking(client, admin, make_client_user)

    mine = items(client, user["headers"])
    assert mine["total"] == 1
    n = mine["items"][0]
    assert n["type"] == "booking_created" and n["booking_id"] == booking["id"] and n["is_read"] is False
    assert "500.00" in n["message"]

    staff = items(client, admin["headers"])
    assert staff["total"] == 1 and staff["items"][0]["priority"] == "low"


def test_status_changes_notify_with_priorities(client, admin, make_client_user):
    user, b = setup_booking(client, admin, make_client_user)
    url = f"/api/bookings/{b['id']}/status"
    client.patch(url, headers=admin["headers"], json={"status": "in_progress"})
    client.patch(url, headers=admin["headers"], json={"status": "cancelled"})

    got = items(client, user["headers"])
    assert got["total"] == 3
    newest = got["items"][0]
    assert newest["type"] == "booking_cancelled" and newest["priority"] == "high"  # скасувала не вона сама

    high = items(client, user["headers"], priority="high")
    assert high["total"] == 1
    assert items(client, user["headers"], type="booking_status")["total"] == 1


def test_client_cancelling_notifies_admins_not_high_for_self(client, admin, make_client_user):
    user, b = setup_booking(client, admin, make_client_user)
    client.patch(f"/api/bookings/{b['id']}/status", headers=user["headers"], json={"status": "cancelled"})

    mine = items(client, user["headers"], type="booking_cancelled")
    assert mine["items"][0]["priority"] == "normal"
    staff = items(client, admin["headers"], type="booking_cancelled")
    assert staff["total"] == 1


def test_master_assignment_notifies_both(client, admin, make_client_user, make_master):
    user, b = setup_booking(client, admin, make_client_user)
    master = make_master()
    client.patch(f"/api/bookings/{b['id']}", headers=admin["headers"], json={"master_id": master["user"]["id"]})

    m = items(client, master["headers"])
    assert m["total"] == 1 and m["items"][0]["priority"] == "high" and m["items"][0]["type"] == "master_assigned"
    assert items(client, user["headers"], type="master_assigned")["total"] == 1


def test_read_unread_delete_and_isolation(client, admin, make_client_user):
    user, b = setup_booking(client, admin, make_client_user)
    other = make_client_user("other@example.com")
    nid = items(client, user["headers"])["items"][0]["id"]

    assert client.get("/api/notifications/unread-count", headers=user["headers"]).json() == {"count": 1}
    assert client.patch(f"/api/notifications/{nid}/read", headers=other["headers"]).status_code == 404
    assert client.delete(f"/api/notifications/{nid}", headers=other["headers"]).status_code == 404

    assert client.patch(f"/api/notifications/{nid}/read", headers=user["headers"]).json()["is_read"] is True
    assert client.get("/api/notifications/unread-count", headers=user["headers"]).json() == {"count": 0}
    assert items(client, user["headers"], is_read="false")["total"] == 0

    client.patch(f"/api/bookings/{b['id']}/status", headers=admin["headers"], json={"status": "in_progress"})
    assert client.post("/api/notifications/read-all", headers=user["headers"]).json() == {"updated": 1}
    assert client.delete(f"/api/notifications/{nid}", headers=user["headers"]).status_code == 204
    assert items(client, user["headers"])["total"] == 1


def test_notifications_require_auth(client):
    assert client.get("/api/notifications").status_code == 401
