from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Усі налаштування беруться зі змінних середовища / файлу .env.

    Секрети й адреси я не хардкожу в коді: так той самий код працює і локально,
    і на хостингу, а .env не потрапляє в git.
    """

    database_url: str = "postgresql+psycopg://carwash:carwash@localhost:5433/carwash"
    frontend_url: str = "http://localhost:5173"

    timezone: str = "Europe/Kyiv"
    work_day_start: int = 9
    work_day_end: int = 20
    slot_step_minutes: int = 30

    seed_admin_password: str = "change-me-please"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
