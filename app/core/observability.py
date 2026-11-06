"""Журнал повільних запитів до БД і метрики Prometheus."""
import logging
import time

from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.config import settings

log = logging.getLogger("carwash.db")

HTTP_REQUESTS = Counter("http_requests_total", "Кількість HTTP-запитів", ["method", "path", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "Тривалість HTTP-запитів", ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.3, 0.5, 1, 2, 5),
)
WS_CONNECTIONS = Gauge("ws_connections", "Кількість відкритих WebSocket-з'єднань")
WS_EVENTS = Counter("ws_events_total", "Кількість вихідних подій WebSocket", ["event"])


def setup_slow_query_log(engine: Engine) -> None:
    """Пише в лог кожен SQL-запит, що виконувався довше за SLOW_QUERY_MS.

    Так знаходимо кандидатів на оптимізацію, а потім аналізуємо їх через EXPLAIN ANALYZE.
    """

    @event.listens_for(engine, "before_cursor_execute")
    def _start(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _finish(conn, cursor, statement, parameters, context, executemany):
        elapsed_ms = (time.perf_counter() - conn.info["query_start"].pop()) * 1000
        if elapsed_ms >= settings.slow_query_ms:
            log.warning("Повільний запит (%.0f мс): %s", elapsed_ms, " ".join(statement.split())[:300])
