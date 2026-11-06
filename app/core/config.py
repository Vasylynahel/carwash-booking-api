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
    # --- Лабораторна 3 ---
    # Додаткові origin-и для Socket.IO (демо-сторінка /demo відкривається з самого бекенду)
    extra_cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    # Якщо задано, Socket.IO працює через Redis і масштабується на кілька копій сервера
    redis_url: str | None = None

    # Пул з'єднань із БД та журнал повільних запитів
    db_pool_size: int = 10
    db_max_overflow: int = 10
    slow_query_ms: int = 200

    # Кеш і журнал подій
    cache_ttl_seconds: int = 60
    events_retention_days: int = 7
    replay_limit: int = 200

    # Ліміт вхідних подій WebSocket на одне з'єднання
    ws_rate_limit_events: int = 30
    ws_rate_limit_window_seconds: int = 10

    # Метрики Prometheus: якщо задано токен, /metrics вимагає заголовок Authorization: Bearer <токен>
    metrics_token: str | None = None

    # Автоматичні «тихі години»
    auto_pricing_enabled: bool = False
    auto_pricing_interval_hours: int = 24
    auto_pricing_weeks: int = 8
    auto_pricing_min_bookings: int = 30   # менше історії, і система нічого не пропонує
    auto_quiet_threshold: float = 0.30    # завантаженість нижче 30%, і година вважається тихою
    auto_discount_max: int = 15           # максимальна автоматична знижка, %
    auto_discount_step: int = 5

    seed_admin_email: str = "admin@example.com"
    seed_admin_password: str = "change-me-please"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_origins(self) -> list[str]:
        extra = [o.strip() for o in self.extra_cors_origins.split(",") if o.strip()]
        return [self.frontend_url, *extra]

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
