"""Демо-історія записів, щоб показати теплову карту й автоматичні «тихі години».

Запуск:  python -m scripts.seed_demo --weeks 8
Спершу виконайте  python -m scripts.seed  (потрібні пости й послуги).

Скрипт генерує правдоподібне навантаження: у будні зайняті ранок і вечір, після обіду
порожньо, на вихідних завантаженість висока. Записи вставляються напряму в БД як виконані
(минулі дати через API створити не можна). Дані завжди однакові (фіксований seed випадкових чисел).
Для перевірки індексів через scripts.explain запустіть із --weeks 104: це десятки тисяч рядків.
"""
import argparse
import random
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Bay, Booking, BookingService, BookingStatus, Car, Service, User, UserRole

DEMO_DOMAIN = "@demo.example.com"


def busy_probability(weekday: int, hour: int) -> float:
    """Ймовірність, що пост зайнятий у цю годину."""
    if weekday >= 5:                       # субота, неділя
        return 0.75 if 10 <= hour < 17 else 0.35
    if 9 <= hour < 12:
        return 0.85                        # ранок: клієнти їдуть перед роботою
    if hour == 12:
        return 0.5
    if 13 <= hour < 17:
        return 0.12                        # після обіду тихо: саме тут має з'явитись знижка
    return 0.6                             # вечір: після роботи


def main(weeks: int) -> None:
    rng = random.Random(42)
    tz = settings.tz
    with SessionLocal() as db:
        bays = list(db.scalars(select(Bay).where(Bay.is_active.is_(True))))
        services = list(db.scalars(select(Service).where(Service.is_active.is_(True), Service.duration_minutes <= 60)))
        if not bays or not services:
            raise SystemExit("Спершу виконайте: python -m scripts.seed")

        if db.scalar(select(User.id).where(User.email.like(f"%{DEMO_DOMAIN}")).limit(1)):
            raise SystemExit("Демо-дані вже створено. Видаліть користувачів *@demo.example.com, щоб почати заново.")

        password_hash = hash_password("demo-password-1")
        clients = [
            User(email=f"client{i}{DEMO_DOMAIN}", password_hash=password_hash, full_name=f"Демо Клієнт {i}",
                 role=UserRole.CLIENT)
            for i in range(1, 7)
        ]
        db.add_all(clients)
        db.flush()
        cars = [Car(owner_id=c.id, brand="Demo", model=f"Model {c.id}", plate_number=f"DM{c.id:04d}XX") for c in clients]
        db.add_all(cars)
        db.flush()

        today = datetime.now(tz).date()
        count = 0
        for days_ago in range(1, weeks * 7 + 1):
            day = today - timedelta(days=days_ago)
            for hour in range(settings.work_day_start, settings.work_day_end):
                for bay in bays:
                    if rng.random() >= busy_probability(day.weekday(), hour):
                        continue
                    service = rng.choice(services)
                    start = datetime.combine(day, time(hour), tzinfo=tz).astimezone(UTC)
                    car = rng.choice(cars)
                    cancelled = rng.random() < 0.05
                    booking = Booking(
                        client_id=car.owner_id, car_id=car.id, bay_id=bay.id,
                        scheduled_at=start, ends_at=start + timedelta(minutes=60),
                        status=BookingStatus.CANCELLED if cancelled else BookingStatus.DONE,
                        total_price=service.price, discount_percent=Decimal("0.00"),
                        items=[BookingService(service_id=service.id, price=service.price,
                                              duration_minutes=service.duration_minutes)],
                    )
                    db.add(booking)
                    count += 1
            db.flush()
        db.commit()
    print(f"Створено {count} записів за {weeks} тижнів ({len(clients)} демо-клієнтів)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=8)
    main(parser.parse_args().weeks)
