import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core import rate_limit
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import User, UserRole


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    # Ліміти вимкнені, щоб тести не впиралися в 429; окремий тест вмикає їх сам.
    # Файли пишуться у тимчасову папку, а не в справжню uploads/
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    rate_limit.reset_limits()


@pytest.fixture()
def client():
    # Тести йдуть на SQLite в пам'яті: швидко й без Docker.
    # Логіку перевіряє повністю; специфічне для Postgres (FOR UPDATE) тут ігнорується.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        with Session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    c.Session = Session
    yield c
    app.dependency_overrides.clear()


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['tokens']['access_token']}"}


@pytest.fixture()
def admin(client):
    with client.Session() as db:
        db.add(
            User(
                email="admin@example.com", password_hash=hash_password("adminpass123"),
                full_name="Адмін", role=UserRole.ADMIN,
            )
        )
        db.commit()
    data = _login(client, "admin@example.com", "adminpass123")
    return {"user": data["user"], "headers": _headers(data)}


@pytest.fixture()
def make_client_user(client):
    """Реєструє клієнта через /auth/register і повертає його дані та заголовки."""

    def factory(email="ivan@example.com", password="password123"):
        r = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "full_name": "Іван Петренко"},
        )
        assert r.status_code == 201, r.text
        return {"user": r.json()["user"], "headers": _headers(r.json()), "tokens": r.json()["tokens"]}

    return factory


@pytest.fixture()
def make_master(client, admin):
    def factory(email="master@example.com", password="masterpass123"):
        r = client.post(
            "/api/users",
            headers=admin["headers"],
            json={"email": email, "password": password, "full_name": "Майстер Олег", "role": "master"},
        )
        assert r.status_code == 201, r.text
        data = _login(client, email, password)
        return {"user": data["user"], "headers": _headers(data)}

    return factory
