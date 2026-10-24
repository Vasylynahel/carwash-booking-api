from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.core.audit import Audit
from app.core.auth import AdminUser
from app.core.errors import BusinessRuleError, NotFoundError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import PricingRule
from app.schemas.common import Page
from app.schemas.pricing import PricingRuleCreate, PricingRuleRead, PricingRuleUpdate

router = APIRouter(prefix="/pricing-rules", tags=["Розумні ціни"])


def _get_or_404(db, rule_id: int) -> PricingRule:
    rule = db.get(PricingRule, rule_id)
    if rule is None:
        raise NotFoundError("Правило не знайдено")
    return rule


@router.post("", response_model=PricingRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(data: PricingRuleCreate, admin: AdminUser, db: DbSession, audit: Audit):
    rule = PricingRule(**data.model_dump())
    db.add(rule)
    db.commit()
    audit.log("pricing_rule.create", admin, "pricing_rule", rule.id)
    return rule


@router.get("", response_model=Page[PricingRuleRead])
def list_rules(
    admin: AdminUser, db: DbSession, pager: Pager, is_active: bool | None = None, weekday: int | None = None
):
    stmt = select(PricingRule).order_by(PricingRule.weekday.nulls_first(), PricingRule.start_time)
    if is_active is not None:
        stmt = stmt.where(PricingRule.is_active.is_(is_active))
    if weekday is not None:
        stmt = stmt.where(PricingRule.weekday == weekday)
    return paginate(db, stmt, pager)


@router.get("/{rule_id}", response_model=PricingRuleRead)
def get_rule(rule_id: int, admin: AdminUser, db: DbSession):
    return _get_or_404(db, rule_id)


@router.patch("/{rule_id}", response_model=PricingRuleRead)
def update_rule(rule_id: int, data: PricingRuleUpdate, admin: AdminUser, db: DbSession, audit: Audit):
    rule = _get_or_404(db, rule_id)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)
    # Порядок часу перевіряємо вже після злиття зі старими значеннями
    if rule.start_time >= rule.end_time:
        db.rollback()
        raise BusinessRuleError("Початок діапазону має бути раніше за його кінець")
    db.commit()
    audit.log("pricing_rule.update", admin, "pricing_rule", rule.id, {"fields": sorted(changes)})
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, admin: AdminUser, db: DbSession, audit: Audit):
    rule = _get_or_404(db, rule_id)
    db.delete(rule)
    db.commit()
    audit.log("pricing_rule.delete", admin, "pricing_rule", rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
