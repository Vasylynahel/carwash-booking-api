import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.jobs import start_jobs, stop_jobs
from app.core.observability import HTTP_LATENCY, HTTP_REQUESTS
from app.core.rate_limit import global_limit
from app.realtime import handlers  # noqa: F401  (реєструє обробники подій Socket.IO)
from app.realtime.sio import sio
from app.routers import (
    analytics, audit_logs, auth, bays, bookings, cars, files, health, notifications,
    pricing, realtime, services, users,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("carwash.http")


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = start_jobs()
    yield
    await stop_jobs(tasks)


app = FastAPI(
    title="Carwash Booking API",
    version="0.3.0",
    description=(
        "Бекенд вебсервісу запису на автомийку та детейлінг. "
        "Лаб. 1: БД, CRUD, валідація. Лаб. 2: JWT, ролі, файли, журнал дій, знижки в тихі години. "
        "Лаб. 3: Socket.IO (сповіщення, події наживо, онлайн-статус), автоматичні тихі години за історією, "
        "кеш, метрики. Події WebSocket описано в docs/WEBSOCKET.md."
    ),
    dependencies=[Depends(global_limit)],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observe(request: Request, call_next):
    """Журнал і метрики кожного запиту. Мітка path — шаблон маршруту (/api/bookings/{booking_id}),
    а не фактичний URL, щоб кількість міток не зростала разом з id."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    HTTP_REQUESTS.labels(request.method, path, response.status_code).inc()
    HTTP_LATENCY.labels(request.method, path).observe(elapsed)
    if path not in ("/health", "/metrics"):
        log.info("%s %s -> %s (%.0f мс)", request.method, request.url.path, response.status_code, elapsed * 1000)
    return response


register_error_handlers(app)

app.include_router(health.router)
for r in (
    auth.router, users.router, cars.router, services.router, bays.router, bookings.router,
    pricing.router, analytics.router, notifications.router, realtime.router, files.router, audit_logs.router,
):
    app.include_router(r, prefix="/api")


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    # Якщо задано METRICS_TOKEN, метрики віддаються лише з ним (Prometheus вміє слати Bearer-токен)
    if settings.metrics_token and request.headers.get("authorization") != f"Bearer {settings.metrics_token}":
        return Response(status_code=401)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/demo", include_in_schema=False)
def demo_page():
    """Проста сторінка для демонстрації WebSocket без фронтенду: відкрийте у двох вікнах."""
    return FileResponse(Path(__file__).parent / "static" / "demo.html")


# Єдина точка входу: Socket.IO обробляє /socket.io, усе інше віддає FastAPI.
# Запуск: uvicorn app.main:application
application = socketio.ASGIApp(sio, other_asgi_app=app, socketio_path="socket.io")
