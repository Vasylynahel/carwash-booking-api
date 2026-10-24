# Імпортую всі моделі в одному місці, щоб Alembic і create_all бачили повну схему
from app.models.audit_log import AuditLog
from app.models.bay import Bay
from app.models.booking import Booking, BookingService
from app.models.car import Car
from app.models.enums import BookingStatus, ServiceCategory, UserRole
from app.models.notification import Notification
from app.models.pricing_rule import PricingRule
from app.models.refresh_token import RefreshToken
from app.models.service import Service
from app.models.stored_file import StoredFile
from app.models.user import User

__all__ = [
    "AuditLog", "Bay", "Booking", "BookingService", "Car", "Notification", "PricingRule",
    "RefreshToken", "Service", "StoredFile", "User",
    "BookingStatus", "ServiceCategory", "UserRole",
]
