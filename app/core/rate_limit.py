"""Простий обмежувач частоти запитів у пам'яті процесу (ковзне вікно на IP-адресу).

Для однієї копії сервера цього достатньо. Якщо запустити кілька копій, лічильники
доведеться тримати в Redis (це буде в розширеній частині лабораторної 3).
"""
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import settings
from app.core.errors import TooManyRequestsError

_hits: dict[str, deque[float]] = defaultdict(deque)


def _check(key: str, limit: int, window: int) -> None:
    now = time.monotonic()
    hits = _hits[key]
    while hits and hits[0] <= now - window:
        hits.popleft()
    if len(hits) >= limit:
        retry_after = int(window - (now - hits[0])) + 1
        raise TooManyRequestsError(
            "Забагато запитів, спробуйте пізніше", headers={"Retry-After": str(retry_after)}
        )
    hits.append(now)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def global_limit(request: Request) -> None:
    if settings.rate_limit_enabled:
        _check(f"global:{_ip(request)}", settings.rate_limit_global, settings.rate_limit_window_seconds)


def auth_limit(request: Request) -> None:
    """Суворіший ліміт для входу, реєстрації та оновлення токенів: захист від підбору паролів."""
    if settings.rate_limit_enabled:
        _check(f"auth:{_ip(request)}", settings.rate_limit_auth, 60)


def reset_limits() -> None:
    _hits.clear()
