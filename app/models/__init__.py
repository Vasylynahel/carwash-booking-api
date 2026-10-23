# Імпортую всі моделі в одному місці, щоб Alembic і create_all бачили повну схему
from app.models.bay import Bay
from app.models.booking import Booking, BookingService
from app.models.car import Car
from app.models.enums import BookingStatus, ServiceCategory, UserRole
from app.models.notification import Notification
from app.models.service import Service
from app.models.user import User

__all__ = [
    "Bay", "Booking", "BookingService", "Car", "Notification", "Service", "User",
    "BookingStatus", "ServiceCategory", "UserRole",
]
