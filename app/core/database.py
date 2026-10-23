from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


# pool_pre_ping перевіряє з'єднання перед використанням, тому після
# перезапуску бази застосунок не падає на «мертвих» з'єднаннях
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Залежність FastAPI: одна сесія на один запит, завжди закривається."""
    with SessionLocal() as db:
        yield db
