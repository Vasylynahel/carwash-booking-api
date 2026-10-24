import jwt

from app.core.config import settings


def test_register_login_me(client, make_client_user):
    u = make_client_user()
    assert u["user"]["role"] == "client"
    assert "password" not in u["user"] and "password_hash" not in u["user"]

    me = client.get("/api/auth/me", headers=u["headers"])
    assert me.status_code == 200 and me.json()["email"] == "ivan@example.com"

    login = client.post("/api/auth/login", json={"email": "IVAN@example.com", "password": "password123"})
    assert login.status_code == 200 and login.json()["tokens"]["token_type"] == "bearer"


def test_register_validation_and_duplicate(client, make_client_user):
    bad = client.post("/api/auth/register", json={"email": "x", "password": "123", "full_name": "A"})
    assert bad.status_code == 422
    assert {d["field"] for d in bad.json()["details"]} >= {"email", "password", "full_name"}

    make_client_user()
    dup = client.post(
        "/api/auth/register",
        json={"email": "ivan@example.com", "password": "password123", "full_name": "Інший"},
    )
    assert dup.status_code == 409


def test_register_cannot_choose_role(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "hacker@example.com", "password": "password123", "full_name": "Хакер", "role": "admin"},
    )
    assert r.status_code == 201 and r.json()["user"]["role"] == "client"


def test_wrong_credentials_same_message(client, make_client_user):
    make_client_user()
    wrong_pass = client.post("/api/auth/login", json={"email": "ivan@example.com", "password": "nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "password123"})
    assert wrong_pass.status_code == unknown.status_code == 401
    assert wrong_pass.json() == unknown.json()


def test_protected_endpoints_need_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/api/cars").status_code == 401


def test_refresh_token_cannot_be_used_as_access(client, make_client_user):
    u = make_client_user()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {u['tokens']['refresh_token']}"})
    assert r.status_code == 401


def test_expired_access_token(client, make_client_user):
    u = make_client_user()
    payload = jwt.decode(u["tokens"]["access_token"], settings.jwt_secret, algorithms=["HS256"])
    payload["exp"] = payload["iat"] - 10
    expired = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_refresh_rotation_and_reuse_detection(client, make_client_user):
    u = make_client_user()
    old = u["tokens"]["refresh_token"]

    first = client.post("/api/auth/refresh", json={"refresh_token": old})
    assert first.status_code == 200
    new = first.json()["refresh_token"]
    assert new != old

    # старий токен відкликано
    assert client.post("/api/auth/refresh", json={"refresh_token": old}).status_code == 401
    # повторне використання відкликаного токена скасувало й новий
    assert client.post("/api/auth/refresh", json={"refresh_token": new}).status_code == 401


def test_logout_revokes_refresh_token(client, make_client_user):
    u = make_client_user()
    rt = u["tokens"]["refresh_token"]
    assert client.post("/api/auth/logout", json={"refresh_token": rt}).status_code == 204
    assert client.post("/api/auth/refresh", json={"refresh_token": rt}).status_code == 401


def test_change_password(client, make_client_user):
    u = make_client_user()
    rt = u["tokens"]["refresh_token"]

    wrong = client.post(
        "/api/auth/change-password", headers=u["headers"],
        json={"current_password": "wrong-pass", "new_password": "newpassword1"},
    )
    assert wrong.status_code == 422  # не 401: сесія чинна

    same = client.post(
        "/api/auth/change-password", headers=u["headers"],
        json={"current_password": "password123", "new_password": "password123"},
    )
    assert same.status_code == 422

    ok = client.post(
        "/api/auth/change-password", headers=u["headers"],
        json={"current_password": "password123", "new_password": "newpassword1"},
    )
    assert ok.status_code == 204
    assert client.post("/api/auth/refresh", json={"refresh_token": rt}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ivan@example.com", "password": "password123"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ivan@example.com", "password": "newpassword1"}).status_code == 200


def test_swagger_form_login(client, make_client_user):
    make_client_user()
    r = client.post("/api/auth/token", data={"username": "ivan@example.com", "password": "password123"})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"


def test_deactivated_user_loses_access(client, admin, make_client_user):
    u = make_client_user()
    r = client.patch(f"/api/users/{u['user']['id']}", headers=admin["headers"], json={"is_active": False})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=u["headers"]).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": u["tokens"]["refresh_token"]}).status_code == 401


def test_rate_limit_on_login(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_auth", 3)
    codes = [
        client.post("/api/auth/login", json={"email": "a@b.com", "password": "whatever1"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "whatever1"})
    assert "retry-after" in r.headers
