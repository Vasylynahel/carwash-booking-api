"""«Розумні ціни»: знижки в тихі години.

Правило задає години (і, за потреби, день тижня), коли пости мало завантажені.
Клієнт, який обирає такий час, платить менше, а автомийка вирівнює завантаження.
Знижки не складаються: діє одна, найбільша.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PricingRule

CENT = Decimal("0.01")


def active_rules(db: Session) -> list[PricingRule]:
    return list(db.scalars(select(PricingRule).where(PricingRule.is_active.is_(True))))


def best_rule(rules: list[PricingRule], local_start: datetime) -> PricingRule | None:
    """Правило з найбільшою знижкою для запису, що починається в local_start (місцевий час)."""
    t = local_start.time()
    matching = [
        r
        for r in rules
        if (r.weekday is None or r.weekday == local_start.weekday()) and r.start_time <= t < r.end_time
    ]
    return max(matching, key=lambda r: r.discount_percent, default=None)


def apply_discount(base: Decimal, percent: Decimal) -> Decimal:
    return (base * (Decimal(100) - percent) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
