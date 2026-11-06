"""Порівняння планів виконання ключових запитів з індексами та без них (лише PostgreSQL).

Запуск:  python -m scripts.explain
Для наочного результату спершу згенеруйте багато даних:  python -m scripts.seed_demo --weeks 104

«Без індексів» не видаляє індекси: у межах транзакції вимикається використання індексного
сканування (SET LOCAL enable_indexscan = off …), тож планувальник змушений читати таблицю цілком.
Усе, що скрипт друкує, виміряно на вашій машині: ці числа й заносьте у звіт.
"""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.database import engine

NOW = datetime.now(UTC)

QUERIES = {
    "Записи за статусом і датою (фільтр адміністратора)": (
        "SELECT * FROM bookings WHERE status = 'done' AND scheduled_at >= :since ORDER BY scheduled_at DESC LIMIT 50",
        {"since": NOW - timedelta(days=30)},
    ),
    "Перетин слотів на посту (перевірка при записі)": (
        "SELECT id FROM bookings WHERE bay_id = 1 AND scheduled_at < :e AND ends_at > :s AND status <> 'cancelled' LIMIT 1",
        {"s": NOW - timedelta(days=3), "e": NOW - timedelta(days=3) + timedelta(hours=1)},
    ),
    "Історія записів за період (аналітика завантаженості)": (
        "SELECT scheduled_at, ends_at FROM bookings WHERE scheduled_at >= :s AND scheduled_at < :e AND status <> 'cancelled'",
        {"s": NOW - timedelta(weeks=8), "e": NOW},
    ),
    "Мої непрочитані сповіщення": (
        "SELECT * FROM notifications WHERE user_id = 1 AND is_read = false ORDER BY created_at DESC LIMIT 20",
        {},
    ),
    "Пропущені події кімнати (відновлення після обриву)": (
        "SELECT * FROM events WHERE room IN ('user:1', 'role:admin', 'all') AND id > 0 ORDER BY id LIMIT 200",
        {},
    ),
}


def run(conn, sql: str, params: dict, indexes: bool) -> tuple[float, str]:
    if not indexes:
        for setting in ("enable_indexscan", "enable_bitmapscan", "enable_indexonlyscan"):
            conn.execute(text(f"SET LOCAL {setting} = off"))
    rows = conn.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {sql}"), params).scalars().all()
    plan = "\n".join(rows)
    ms = float(re.search(r"Execution Time: ([\d.]+) ms", plan).group(1))
    kind = "Index" if "Index" in plan or "Bitmap" in plan else "Seq Scan"
    return ms, kind


def main() -> None:
    with engine.connect() as conn:
        counts = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("bookings", "notifications", "events")}
        print("Рядків у таблицях:", counts, "\n")
        print(f"{'Запит':<58}{'з індексами':>16}{'без індексів':>18}")
        for title, (sql, params) in QUERIES.items():
            with_ms, with_kind = run(conn, sql, params, True)
            conn.rollback()
            without_ms, without_kind = run(conn, sql, params, False)
            conn.rollback()
            print(f"{title:<58}{with_ms:>9.2f} мс ({with_kind[:3]}){without_ms:>9.2f} мс ({without_kind[:3]})")
        print("\nПовний план конкретного запиту: EXPLAIN (ANALYZE, BUFFERS) <SQL> у psql.")


if __name__ == "__main__":
    main()
