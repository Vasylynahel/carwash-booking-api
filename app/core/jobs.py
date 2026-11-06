"""Фонові завдання, що крутяться разом із сервером (замість окремої черги задач).

1. Прибирання старого журналу подій (щогодини).
2. Автоматичний перерахунок «тихих годин» (за замовчуванням вимкнено: AUTO_PRICING_ENABLED).

Для серйозного навантаження такі завдання виносять у чергу (Celery, RQ, ARQ) з окремим процесом-виконавцем;
для курсової вистачає простих циклів asyncio.
"""
import asyncio
import contextlib
import logging

import anyio.to_thread

from app.core import database
from app.core.config import settings
from app.realtime import events as event_store
from app.services import analytics_service

log = logging.getLogger("carwash.jobs")


def _cleanup_events() -> int:
    with database.SessionLocal() as db:
        return event_store.cleanup(db)


def _recalculate_pricing() -> tuple[bool, int]:
    with database.SessionLocal() as db:
        occ, suggestions = analytics_service.apply_suggestions(db, settings.auto_pricing_weeks)
        return occ.enough_data, len(suggestions)


async def _loop(name: str, interval_seconds: float, func, first_delay: float) -> None:
    await asyncio.sleep(first_delay)
    while True:
        try:
            result = await anyio.to_thread.run_sync(func)
            log.info("Завдання %s виконано: %s", name, result)
        except Exception:
            # Помилка одного запуску не повинна зупиняти завдання назавжди
            log.exception("Завдання %s завершилось помилкою", name)
        await asyncio.sleep(interval_seconds)


def start_jobs() -> list[asyncio.Task]:
    tasks = [asyncio.create_task(_loop("cleanup_events", 3600, _cleanup_events, first_delay=60))]
    if settings.auto_pricing_enabled:
        tasks.append(
            asyncio.create_task(
                _loop("auto_pricing", settings.auto_pricing_interval_hours * 3600, _recalculate_pricing, first_delay=30)
            )
        )
    return tasks


async def stop_jobs(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await t
