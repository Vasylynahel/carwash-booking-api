from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401  (щоб усі моделі потрапили в метадані)
from app.core.config import settings
from app.core.database import Base

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # URL беру з .env через settings, а не з alembic.ini, щоб пароль не лежав у репозиторії
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
