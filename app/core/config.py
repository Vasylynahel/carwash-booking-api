from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Усі налаштування беруться зі змінних середовища / файлу .env.

    Секрети й адреси я не хардкожу в коді: так той самий код працює і локально,
    і на хостингу, а .env не потрапляє в git.
    """

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://carwash:carwash@localhost:5433/carwash"
    frontend_url: str = "http://localhost:5173"

    # Робочий день і слоти
    timezone: str = "Europe/Kyiv"
    work_day_start: int = 9
    work_day_end: int = 20
    slot_step_minutes: int = 30

    # JWT: два різні секрети, щоб refresh-токен не можна було підсунути як access і навпаки
    jwt_secret: str = "change-me-access-secret-0123456789abcdef"
    refresh_token_secret: str = "change-me-refresh-secret-0123456789abcdef"
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 7

    # Файли
    upload_dir: str = "uploads"
    max_file_size: int = 5 * 1024 * 1024  # 5 МБ
    max_files_per_request: int = 5

    # Обмеження частоти запитів (на одну IP-адресу)
    rate_limit_enabled: bool = True
    rate_limit_global: int = 300           # запитів за вікно
    rate_limit_window_seconds: int = 900   # 15 хвилин
    rate_limit_auth: int = 10              # спроб входу/реєстрації за хвилину

    # .local та інші службові домени email-validator відхиляє, тому адмін за замовчуванням на example.com
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: str = "change-me-please"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)

    @model_validator(mode="after")
    def forbid_default_secrets_in_production(self):
        # Щоб не задеплоїти сервер із секретами з репозиторію
        if self.app_env == "production" and any(
            s.startswith("change-me") for s in (self.jwt_secret, self.refresh_token_secret)
        ):
            raise ValueError("У production потрібно задати власні JWT_SECRET і REFRESH_TOKEN_SECRET")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
