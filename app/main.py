from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import register_error_handlers
from app.routers import bays, bookings, cars, health, services, users

app = FastAPI(
    title="Carwash Booking API",
    version="0.1.0",
    description=(
        "Бекенд вебсервісу запису на автомийку та детейлінг. "
        "Лабораторна робота 1: структура БД, CRUD, валідація, обробка помилок."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(health.router)
for r in (users.router, cars.router, services.router, bays.router, bookings.router):
    app.include_router(r, prefix="/api")
