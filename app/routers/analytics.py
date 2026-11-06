from typing import Annotated

from fastapi import APIRouter, Query

from app.core.audit import Audit
from app.core.auth import AdminUser
from app.core.config import settings
from app.deps import DbSession
from app.realtime import publisher
from app.services import analytics_service as svc

router = APIRouter(prefix="/analytics", tags=["Аналітика та розумні ціни"])

Weeks = Annotated[int, Query(ge=2, le=26, description="За скільки останніх тижнів рахувати")]


def _suggestion_dict(s: svc.Suggestion) -> dict:
    return {
        "weekday": s.weekday,
        "start_hour": s.start_hour,
        "end_hour": s.end_hour,
        "discount_percent": s.discount_percent,
        "avg_load": s.avg_load,
        "name": s.name,
    }


@router.get("/occupancy", summary="Теплова карта завантаженості постів (день тижня × година)")
def occupancy(admin: AdminUser, db: DbSession, weeks: Weeks = 8):
    occ = svc.occupancy(db, weeks)
    return {
        "weeks": occ.weeks,
        "bays": occ.bays,
        "bookings": occ.bookings,
        "enough_data": occ.enough_data,
        "min_bookings": settings.auto_pricing_min_bookings,
        "cells": occ.cells,  # load: 0 — пости порожні, 1 — зайняті весь час
    }


@router.get("/quiet-hours", summary="Пропозиції знижок на тихі години за історією записів")
def quiet_hours(admin: AdminUser, db: DbSession, weeks: Weeks = 8):
    occ = svc.occupancy(db, weeks)
    return {
        "enough_data": occ.enough_data,
        "bookings": occ.bookings,
        "min_bookings": settings.auto_pricing_min_bookings,
        "threshold": settings.auto_quiet_threshold,
        "suggestions": [_suggestion_dict(s) for s in svc.suggest(occ)],
    }


@router.post("/quiet-hours/apply", summary="Застосувати пропозиції: створити автоматичні правила знижок")
def apply_quiet_hours(admin: AdminUser, db: DbSession, audit: Audit, weeks: Weeks = 8):
    occ, suggestions = svc.apply_suggestions(db, weeks)
    if occ.enough_data:
        audit.log("pricing.auto_apply", admin, "pricing_rule", None, {"rules": len(suggestions), "weeks": weeks})
        publisher.publish_catalog("pricing_rule", None, "auto_applied")
    return {
        "applied": occ.enough_data,
        "enough_data": occ.enough_data,
        "bookings": occ.bookings,
        "min_bookings": settings.auto_pricing_min_bookings,
        "rules": [_suggestion_dict(s) for s in suggestions],
    }
