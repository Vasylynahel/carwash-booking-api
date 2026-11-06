"""«Розумні ціни»: знижки в тихі години.

Правило задає години (і, за потреби, день тижня), коли пости мало завантажені.
Клієнт, який обирає такий час, платить менше, а автомийка вирівнює завантаження.

Правила бувають ручні (їх створює адміністратор) і автоматичні (їх рахує система за історією,
див. analytics_service). Якщо на час діє хоч одне ручне правило, воно має пріоритет:
адміністратор завжди може перекрити рішення системи. Серед правил одного типу діє
одна, найбільша знижка (знижки не складаються).
"""
from dataclasses import dataclass
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import cache
from app.core.config import settings
from app.models import PricingRule

CENT = Decimal("0.01")
CACHE_PREFIX = "pricing:"


@dataclass(frozen=True)
class RuleData:
    """Знімок правила без прив'язки до сесії БД: такі об'єкти безпечно тримати в кеші між запитами."""

    id: int
    name: str
    weekday: int | None
    start_time: time
    end_time: time
    discount_percent: Decimal
    is_auto: bool


def active_rules(db: Session) -> list[RuleData]:
    def load() -> list[RuleData]:
        rows = db.scalars(select(PricingRule).where(PricingRule.is_active.is_(True)))
        return [
            RuleData(r.id, r.name, r.weekday, r.start_time, r.end_time, r.discount_percent, r.is_auto)
            for r in rows
        ]

    # Правила читаються при кожному перегляді слотів і створенні запису, а змінюються рідко
    return cache.get_or_set(f"{CACHE_PREFIX}active", settings.cache_ttl_seconds, load)


def invalidate_rules() -> None:
    cache.invalidate(CACHE_PREFIX)


def best_rule(rules: list[RuleData], local_start: datetime) -> RuleData | None:
    """Правило з найбільшою знижкою для запису, що починається в local_start (місцевий час)."""
    t = local_start.time()
    matching = [
        r
        for r in rules
        if (r.weekday is None or r.weekday == local_start.weekday()) and r.start_time <= t < r.end_time
    ]
    manual = [r for r in matching if not r.is_auto]
    pool = manual or matching
    return max(pool, key=lambda r: r.discount_percent, default=None)


def apply_discount(base: Decimal, percent: Decimal) -> Decimal:
    return (base * (Decimal(100) - percent) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
