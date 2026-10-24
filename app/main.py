from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.rate_limit import global_limit
from app.routers import (
    audit_logs, auth, bays, bookings, cars, files, health, pricing, services, users,
)

app = FastAPI(
    title="Carwash Booking API",
    version="0.1.0",
    description=(
        "Бекенд вебсервісу запису на автомийку та детейлінг. "
        "Лаб. 1: структура БД, CRUD, валідація, помилки. "
        "Лаб. 2: JWT-автентифікація, ролі, refresh-токени, файли, журнал дій, "
        "обмеження частоти запитів, розумні ціни (знижки в тихі години)."
    ),
    dependencies=[Depends(global_limit)],
)

# Дозволяю запити з адреси клієнта (Vite), щоб у лабах 4–6 React міг ходити до API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(health.router)
for r in (
    auth.router, users.router, cars.router, services.router, bays.router,
    bookings.router, pricing.router, files.router, audit_logs.router,
):
    app.include_router(r, prefix="/api")
