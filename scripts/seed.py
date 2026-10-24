"""Початкові дані: адмін, три пости й каталог із 14 послуг.

Запуск із кореня проєкту:  python -m scripts.seed
Скрипт можна запускати повторно: те, що вже є, він не дублює.
Ціни орієнтовні, їх легко підправити нижче.
"""
from datetime import time
from decimal import Decimal

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Bay, PricingRule, Service, ServiceCategory, User, UserRole

W, P, A, D = (
    ServiceCategory.WASH,
    ServiceCategory.PACKAGE,
    ServiceCategory.ADDON,
    ServiceCategory.DETAILING,
)

# (назва, категорія, тривалість у хвилинах, ціна в грн, опис)
SERVICES = [
    ("Безконтактна мийка", W, 20, 250, "Піна, змив і сушка без щіток"),
    ("Експрес-мийка кузова", W, 30, 350, "Миття кузова, колісних дисків і сушка"),
    ("Комплексна мийка", W, 50, 550, "Кузов, дні порогів, скло та пилосос салону"),
    ("Пакет «Стандарт»", P, 60, 750, "Комплексна мийка + чорніння гуми"),
    ("Пакет «Преміум»", P, 90, 1300, "Комплексна мийка, віск, хімчистка килимків"),
    ("Хімчистка килимків", A, 30, 300, "Глибоке очищення гумових і текстильних килимків"),
    ("Чорніння шин", A, 10, 100, "Нанесення поліролю на гуму"),
    ("Очищення двигуна", A, 30, 400, "М'яке очищення моторного відсіку"),
    ("Озонація салону", A, 30, 350, "Усунення запахів"),
    ("Полірування фар", D, 60, 600, "Відновлення прозорості фар"),
    ("Воскування кузова", D, 60, 700, "Нанесення захисного воску"),
    ("Хімчистка салону", D, 180, 3000, "Повна хімчистка тканини та шкіри"),
    ("Полірування кузова", D, 240, 4500, "Видалення дрібних подряпин і голограм"),
    ("Керамічне покриття", D, 480, 9500, "Захисне нанокерамічне покриття кузова"),
]

BAYS = ["Пост 1", "Пост 2", "Пост 3"]

# Стартові правила «тихих годин»: (назва, день тижня або None, з, до, знижка %)
PRICING_RULES = [
    ("Ранкова знижка", None, time(9, 0), time(11, 0), 10),
    ("Тихий вівторок", 1, time(13, 0), time(17, 0), 15),
    ("Тиха середа", 2, time(13, 0), time(17, 0), 15),
    ("Тихий четвер", 3, time(13, 0), time(17, 0), 15),
]


def main() -> None:
    with SessionLocal() as db:
        if not db.scalar(select(User.id).where(User.email == settings.seed_admin_email)):
            db.add(
                User(
                    email=settings.seed_admin_email,
                    password_hash=hash_password(settings.seed_admin_password),
                    full_name="Адміністратор",
                    role=UserRole.ADMIN,
                )
            )
        for name in BAYS:
            if not db.scalar(select(Bay.id).where(Bay.name == name)):
                db.add(Bay(name=name))
        for name, category, minutes, price, description in SERVICES:
            if not db.scalar(select(Service.id).where(Service.name == name)):
                db.add(
                    Service(
                        name=name,
                        category=category,
                        duration_minutes=minutes,
                        price=Decimal(price),
                        description=description,
                    )
                )
        for name, weekday, start, end, percent in PRICING_RULES:
            if not db.scalar(select(PricingRule.id).where(PricingRule.name == name)):
                db.add(
                    PricingRule(
                        name=name, weekday=weekday, start_time=start, end_time=end,
                        discount_percent=Decimal(percent),
                    )
                )
        db.commit()
    print("Готово: адмін, пости, каталог послуг і правила знижок додано")


if __name__ == "__main__":
    main()
