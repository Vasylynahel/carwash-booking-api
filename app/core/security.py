import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.errors import UnauthorizedError

# PasswordHasher() за замовчуванням — це Argon2id із рекомендованими параметрами
_hasher = PasswordHasher()
ALGORITHM = "HS256"

# Хеш «порожнього» пароля: на ньому проводимо перевірку, коли email не знайдено,
# щоб час відповіді не видавав, чи існує такий користувач
DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, datetime]:
    """Повертає токен і час його завершення. jti робить кожен токен унікальним."""
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.refresh_token_expires_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expires,
    }
    return jwt.encode(payload, settings.refresh_token_secret, algorithm=ALGORITHM), expires


def decode_token(token: str, token_type: str) -> dict:
    secret = settings.jwt_secret if token_type == "access" else settings.refresh_token_secret
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise UnauthorizedError("Термін дії токена минув") from None
    except jwt.InvalidTokenError:
        raise UnauthorizedError("Недійсний токен") from None
    if payload.get("type") != token_type:
        raise UnauthorizedError("Недійсний токен")
    return payload


def hash_token(token: str) -> str:
    # У базі зберігається лише SHA-256 від refresh-токена: навіть якщо базу витечуть,
    # самих токенів зловмисник не отримає
    return hashlib.sha256(token.encode()).hexdigest()
