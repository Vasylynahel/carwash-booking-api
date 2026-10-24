from decimal import Decimal

from tests.helpers import at, day_with_weekday, make_bay, make_car, make_service

TUESDAY, WEDNESDAY = 1, 2


def rule(client, admin, **over):
    payload = {
        "name": "Тихий вівторок", "weekday": TUESDAY,
        "start_time": "13:00:00", "end_time": "17:00:00", "discount_percent": "15",
        **over,
    }
    return client.post("/api/pricing-rules", headers=admin["headers"], json=payload)


def slots(client, day, service_id):
    r = client.get("/api/bookings/availability", params={"date": day.isoformat(), "service_ids": [service_id]})
    assert r.status_code == 200, r.text
    return {s["start"][11:16]: s for s in r.json()}


def test_rules_are_admin_only(client, admin, make_client_user):
    u = make_client_user()
    assert rule(client, admin).status_code == 201
    assert client.post("/api/pricing-rules", headers=u["headers"], json={}).status_code == 403
    assert client.get("/api/pricing-rules", headers=u["headers"]).status_code == 403
    assert client.get("/api/pricing-rules").status_code == 401


def test_rule_validation(client, admin):
    assert rule(client, admin, start_time="17:00:00", end_time="13:00:00").status_code == 422
    assert rule(client, admin, discount_percent="75").status_code == 422
    assert rule(client, admin, discount_percent="0").status_code == 422
    assert rule(client, admin, weekday=9).status_code == 422

    ok = rule(client, admin).json()
    # PATCH, що після злиття дає початок пізніше за кінець
    bad = client.patch(f"/api/pricing-rules/{ok['id']}", headers=admin["headers"], json={"start_time": "18:00:00"})
    assert bad.status_code == 422
    good = client.patch(f"/api/pricing-rules/{ok['id']}", headers=admin["headers"], json={"discount_percent": "20"})
    assert good.status_code == 200 and Decimal(good.json()["discount_percent"]) == 20


def test_slots_show_discount(client, admin):
    service = make_service(client, admin["headers"], price="500.00")
    make_bay(client, admin["headers"])
    rule(client, admin)

    tue = slots(client, day_with_weekday(TUESDAY), service["id"])
    assert tue["13:00"]["discount_percent"] == "15.00" and tue["13:00"]["price"] == "425.00"
    assert tue["13:00"]["base_price"] == "500.00" and tue["13:00"]["rule_name"] == "Тихий вівторок"
    assert tue["12:30"]["price"] == "500.00" and tue["12:30"]["rule_name"] is None
    assert tue["16:30"]["discount_percent"] == "15.00"
    assert tue["17:00"]["discount_percent"] == "0.00"  # кінець діапазону не входить

    wed = slots(client, day_with_weekday(WEDNESDAY), service["id"])
    assert wed["13:00"]["discount_percent"] == "0.00"  # правило лише для вівторка


def test_largest_discount_wins_and_inactive_ignored(client, admin):
    service = make_service(client, admin["headers"])
    make_bay(client, admin["headers"])
    rule(client, admin, name="Щодня", weekday=None, start_time="13:00:00", end_time="15:00:00", discount_percent="10")
    big = rule(client, admin, name="Вівторок", discount_percent="15").json()

    tue = slots(client, day_with_weekday(TUESDAY), service["id"])
    assert tue["14:00"]["discount_percent"] == "15.00"  # не 25: знижки не складаються

    client.patch(f"/api/pricing-rules/{big['id']}", headers=admin["headers"], json={"is_active": False})
    tue = slots(client, day_with_weekday(TUESDAY), service["id"])
    assert tue["14:00"]["discount_percent"] == "10.00"


def test_booking_gets_discount_and_keeps_it(client, admin, make_client_user):
    user = make_client_user()
    service = make_service(client, admin["headers"], price="500.00")
    make_bay(client, admin["headers"])
    car = make_car(client, user["headers"])
    r = rule(client, admin).json()
    tuesday = day_with_weekday(TUESDAY)

    discounted = client.post(
        "/api/bookings", headers=user["headers"],
        json={"car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": at(tuesday, 14)},
    ).json()
    assert discounted["discount_percent"] == "15.00" and discounted["total_price"] == "425.00"
    assert discounted["items"][0]["price"] == "500.00"  # у позиції лишається ціна каталогу

    full = client.post(
        "/api/bookings", headers=user["headers"],
        json={"car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": at(tuesday, 18)},
    ).json()
    assert full["discount_percent"] == "0.00" and full["total_price"] == "500.00"

    # зміна чи видалення правила не чіпає вже створений запис
    client.delete(f"/api/pricing-rules/{r['id']}", headers=admin["headers"])
    again = client.get(f"/api/bookings/{discounted['id']}", headers=user["headers"]).json()
    assert again["total_price"] == "425.00"


def test_discount_rounding(client, admin, make_client_user):
    user = make_client_user()
    service = make_service(client, admin["headers"], price="333.33")
    make_bay(client, admin["headers"])
    car = make_car(client, user["headers"])
    rule(client, admin, discount_percent="12.5")
    b = client.post(
        "/api/bookings", headers=user["headers"],
        json={"car_id": car["id"], "service_ids": [service["id"]], "scheduled_at": at(day_with_weekday(TUESDAY), 14)},
    ).json()
    assert b["total_price"] == "291.66"  # 333.33 * 0.875 = 291.66375
