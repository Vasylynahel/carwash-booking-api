from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings
from app.core.observability import setup_slow_query_log


class Base(DeclarativeBase):
    pass


# pool_pre_ping перевіряє з'єднання перед використанням, тому після
# перезапуску бази застосунок не падає на «мертвих» з'єднаннях.
# Розмір пулу задається через .env: на безкоштовному хостингу ліміт з'єднань зазвичай малий
_pool_args = (
    {} if settings.database_url.startswith("sqlite")
    else {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow}
)
engine = create_engine(settings.database_url, pool_pre_ping=True, **_pool_args)
setup_slow_query_log(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Залежність FastAPI: одна сесія на один запит, завжди закривається."""
    with SessionLocal() as db:
        yield db
