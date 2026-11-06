"""Завантаженість постів за історією записів і автоматичні «тихі години».

Для кожної пари (день тижня, година) рахуємо, яку частку часу пости були зайняті
в середньому за останні N тижнів. Година з низькою завантаженістю вважається тихою, і для
неї пропонується знижка: чим тихіше, тим більша (до AUTO_DISCOUNT_MAX).

Захист від хибних висновків: у нової автомийки історії мало, і майже всі години «порожні».
Тому, поки записів менше за AUTO_PRICING_MIN_BOOKINGS, система нічого не пропонує.
"""
import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import cache
from app.core.config import settings
from app.models import Bay, Booking, BookingStatus, PricingRule
from app.services import pricing_service

WEEKDAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]


@dataclass
class Occupancy:
    weeks: int
    bays: int
    bookings: int
    enough_data: bool
    cells: list[dict]  # {weekday, hour, load}


@dataclass
class Suggestion:
    weekday: int
    start_hour: int
    end_hour: int  # не включно
    discount_percent: int
    avg_load: float

    @property
    def name(self) -> str:
        return f"Авто: {WEEKDAYS[self.weekday]} {self.start_hour:02d}:00–{self.end_hour:02d}:00"


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def compute_occupancy(db: Session, weeks: int) -> Occupancy:
    tz = settings.tz
    now = datetime.now(UTC)
    period_start = now - timedelta(weeks=weeks)

    bays = db.scalar(select(func.count()).select_from(Bay).where(Bay.is_active.is_(True))) or 0
    rows = db.execute(
        select(Booking.scheduled_at, Booking.ends_at).where(
            Booking.scheduled_at >= period_start,
            Booking.scheduled_at < now,
            Booking.status != BookingStatus.CANCELLED,
        )
    ).all()

    # Скільки хвилин зайнято в кожній парі (день тижня, година): розкладаємо кожен запис по годинах
    busy: dict[tuple[int, int], float] = {}
    for start, end in rows:
        cur, end = _utc(start), _utc(end)
        while cur < end:
            next_hour = cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            seg_end = min(end, next_hour)
            local = cur.astimezone(tz)
            key = (local.weekday(), local.hour)
            busy[key] = busy.get(key, 0.0) + (seg_end - cur).total_seconds() / 60
            cur = seg_end

    capacity = max(bays, 1) * 60 * weeks  # хвилин, які пости могли б відпрацювати в цю годину за період
    cells = [
        {"weekday": wd, "hour": h, "load": round(min(busy.get((wd, h), 0.0) / capacity, 1.0), 3)}
        for wd in range(7)
        for h in range(settings.work_day_start, settings.work_day_end)
    ]
    return Occupancy(
        weeks=weeks,
        bays=bays,
        bookings=len(rows),
        enough_data=len(rows) >= settings.auto_pricing_min_bookings and bays > 0,
        cells=cells,
    )


def occupancy(db: Session, weeks: int) -> Occupancy:
    # Аналітика важка (проходить по всій історії), а змінюється повільно: кешуємо на кілька хвилин
    return cache.get_or_set(f"analytics:occupancy:{weeks}", settings.cache_ttl_seconds * 5,
                            lambda: compute_occupancy(db, weeks))


def discount_for_load(load: float) -> int:
    """Чим менша завантаженість, тим більша знижка: від кроку й до максимуму. Для зайнятих годин 0."""
    threshold = settings.auto_quiet_threshold
    if load >= threshold:
        return 0
    raw = settings.auto_discount_max * (1 - load / threshold)
    step = settings.auto_discount_step
    # +1e-9: інакше 15 * (1 - 0.2/0.3) дає 4.999999… через похибку float, і знижка 5% зникає
    return int(math.floor(raw / step + 1e-9) * step)


def suggest(occ: Occupancy) -> list[Suggestion]:
    """Зливає сусідні тихі години дня в один блок, а знижку рахує за середньою завантаженістю блоку.

    Так замість дрібних правил на кшталт «13:00–14:00 −10%, 14:00–15:00 −5%» адміністратор
    отримує одне зрозуміле: «13:00–17:00 −5%». Година тиха, якщо її знижка за формулою не нульова.
    """
    if not occ.enough_data:
        return []
    by_day: dict[int, list[tuple[int, float]]] = {}
    for c in occ.cells:
        by_day.setdefault(c["weekday"], []).append((c["hour"], c["load"]))

    result: list[Suggestion] = []
    for weekday, hours in by_day.items():
        block: list[tuple[int, float]] = []

        def close(block=block, weekday=weekday):
            if not block:
                return
            avg = sum(load for _, load in block) / len(block)
            discount = discount_for_load(avg)
            if discount > 0:
                result.append(Suggestion(weekday, block[0][0], block[-1][0] + 1, discount, round(avg, 3)))

        for hour, load in hours:
            if discount_for_load(load) > 0 and (not block or block[-1][0] == hour - 1):
                block.append((hour, load))
            else:
                close()
                block.clear()
                if discount_for_load(load) > 0:
                    block.append((hour, load))
        close()
    return result


def apply_suggestions(db: Session, weeks: int) -> tuple[Occupancy, list[Suggestion]]:
    """Замінює всі автоматичні правила новими. Ручні правила не чіпає.

    Якщо даних замало, нічого не змінює: краще лишити попередні правила, ніж затвердити хибні.
    """
    occ = compute_occupancy(db, weeks)  # без кешу: застосовуємо свіжі дані
    if not occ.enough_data:
        return occ, []
    suggestions = suggest(occ)

    db.execute(delete(PricingRule).where(PricingRule.is_auto.is_(True)))
    for s in suggestions:
        db.add(
            PricingRule(
                name=s.name,
                weekday=s.weekday,
                start_time=time(s.start_hour),
                end_time=time(s.end_hour) if s.end_hour < 24 else time(23, 59),
                discount_percent=Decimal(s.discount_percent),
                is_active=True,
                is_auto=True,
            )
        )
    db.commit()
    pricing_service.invalidate_rules()
    cache.invalidate("analytics:")
    return occ, suggestions
