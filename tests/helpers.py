from datetime import date, datetime, timedelta

from app.core.config import settings


def day_with_weekday(weekday: int) -> date:
    """Найближча майбутня дата з потрібним днем тижня (0 — понеділок)."""
    d = datetime.now(settings.tz).date() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


def at(day: date, hour: int, minute: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=settings.tz).isoformat()


def tomorrow_at(hour: int, minute: int = 0) -> str:
    return at(datetime.now(settings.tz).date() + timedelta(days=1), hour, minute)


def make_service(client, headers, name="Комплексна мийка", minutes=60, price="500.00"):
    r = client.post(
        "/api/services", headers=headers,
        json={"name": name, "category": "wash", "duration_minutes": minutes, "price": price},
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_bay(client, headers, name="Пост 1"):
    r = client.post("/api/bays", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def make_car(client, headers, plate="AA1234BB", **extra):
    r = client.post(
        "/api/cars", headers=headers,
        json={"brand": "Skoda", "model": "Octavia", "plate_number": plate, **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()
