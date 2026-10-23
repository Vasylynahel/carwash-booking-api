import enum


class UserRole(str, enum.Enum):
    CLIENT = "client"
    MASTER = "master"
    ADMIN = "admin"


class ServiceCategory(str, enum.Enum):
    WASH = "wash"            # базова мийка
    PACKAGE = "package"      # комплексні пакети
    ADDON = "addon"          # додаткові послуги
    DETAILING = "detailing"  # детейлінг


class BookingStatus(str, enum.Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"
