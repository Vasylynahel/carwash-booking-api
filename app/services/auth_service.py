from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import UnauthorizedError
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas.auth import TokenPair


def issue_tokens(db: Session, user: User) -> TokenPair:
    access = create_access_token(user.id, user.role.value)
    refresh, expires = create_refresh_token(user.id)
    db.add(RefreshToken(token_hash=hash_token(refresh), user_id=user.id, expires_at=expires))
    db.commit()
    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expires_minutes * 60,
    )


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.lower()))
    # Якщо користувача немає, все одно рахуємо хеш: інакше за часом відповіді
    # можна було б вгадувати, які email зареєстровані
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if user is None or not ok or not user.is_active:
        return None
    return user


def revoke_all(db: Session, user_id: int) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()


def rotate_refresh_token(db: Session, refresh_token: str) -> tuple[User, TokenPair]:
    """Обмінює refresh-токен на нову пару. Старий токен відкликається (ротація)."""
    decode_token(refresh_token, "refresh")  # перевіряє підпис і термін дії

    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token)))
    if stored is None:
        raise UnauthorizedError("Недійсний refresh-токен")

    if stored.revoked_at is not None:
        # Відкликаний токен пред'явили вдруге: схоже на викрадення.
        # Скасовуємо всі токени користувача, і йому доведеться увійти заново
        revoke_all(db, stored.user_id)
        raise UnauthorizedError("Недійсний refresh-токен")

    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Обліковий запис недоступний")

    stored.revoked_at = datetime.now(UTC)
    db.commit()
    return user, issue_tokens(db, user)


def revoke_token(db: Session, refresh_token: str) -> int | None:
    """Вихід: відкликає один токен. Повертає id користувача, якщо токен знайдено."""
    stored = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(refresh_token), RefreshToken.revoked_at.is_(None)
        )
    )
    if stored is None:
        return None
    stored.revoked_at = datetime.now(UTC)
    db.commit()
    return stored.user_id
