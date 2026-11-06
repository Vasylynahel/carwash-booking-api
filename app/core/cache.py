"""Невеликий кеш у пам'яті процесу з терміном життя запису (TTL) і скиданням за префіксом.

Кешуємо лише те, що часто читається й рідко змінюється (правила знижок, результати аналітики).
Після зміни даних кеш скидається вручну (`invalidate`), інакше користувачі бачили б застаріле.
Кеш один на процес: якщо запустити кілька копій сервера, його варто винести в Redis.
"""
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_store: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def get_or_set(key: str, ttl: float, factory: Callable[[], T]) -> T:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = factory()  # обчислюємо поза блокуванням, щоб не гальмувати інші потоки
    with _lock:
        _store[key] = (now + ttl, value)
    return value


def invalidate(prefix: str) -> None:
    with _lock:
        for key in [k for k in _store if k.startswith(prefix)]:
            del _store[key]


def clear() -> None:
    with _lock:
        _store.clear()
