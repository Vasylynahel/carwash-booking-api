from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import or_, select

from app.core.audit import Audit
from app.core.auth import AdminUser, CurrentUser
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.pagination import paginate
from app.core.security import hash_password
from app.deps import DbSession, Pager
from app.models import User, UserRole
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["Користувачі"])

# Що може змінювати про себе звичайний користувач; решту (роль, активність) — лише адмін
SELF_EDITABLE = {"full_name", "phone", "email"}


def _get_or_404(db, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("Користувача не знайдено")
    return user


def _ensure_email_free(db, email: str, exclude_id: int | None = None) -> None:
    stmt = select(User.id).where(User.email == email.lower())
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    if db.scalar(stmt) is not None:
        raise ConflictError("Користувач з таким email уже існує")


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Створити користувача з будь-якою роллю (адміністратор)",
)
def create_user(data: UserCreate, admin: AdminUser, db: DbSession, audit: Audit):
    # Так адміністратор заводить майстрів та інших адмінів; клієнти реєструються через /auth/register
    _ensure_email_free(db, data.email)
    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=data.role,
    )
    db.add(user)
    db.commit()
    audit.log("user.create", admin, "user", user.id, {"role": user.role.value})
    return user


@router.get("", response_model=Page[UserRead])
def list_users(
    admin: AdminUser,
    db: DbSession,
    pager: Pager,
    search: Annotated[str | None, Query(max_length=100, description="Пошук за іменем або email")] = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
):
    stmt = select(User).order_by(User.id)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    return paginate(db, stmt, pager)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, current: CurrentUser, db: DbSession):
    if current.role != UserRole.ADMIN and current.id != user_id:
        raise ForbiddenError("Можна переглядати лише власний профіль")
    return _get_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserUpdate, current: CurrentUser, db: DbSession, audit: Audit):
    is_admin = current.role == UserRole.ADMIN
    if not is_admin and current.id != user_id:
        raise ForbiddenError("Можна змінювати лише власний профіль")

    user = _get_or_404(db, user_id)
    changes = data.model_dump(exclude_unset=True)
    if not is_admin and not set(changes) <= SELF_EDITABLE:
        raise ForbiddenError("Роль, статус і пароль через цей ендпоїнт змінює лише адміністратор")

    if "email" in changes:
        changes["email"] = changes["email"].lower()
        _ensure_email_free(db, changes["email"], exclude_id=user_id)
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    audit.log("user.update", current, "user", user.id, {"fields": sorted(data.model_dump(exclude_unset=True))})
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: AdminUser, db: DbSession, audit: Audit):
    if user_id == admin.id:
        raise BusinessRuleError("Не можна видалити власний обліковий запис")
    user = _get_or_404(db, user_id)
    if user.cars:
        raise ConflictError("У користувача є автомобілі; видаліть їх або деактивуйте обліковий запис")
    db.delete(user)
    db.commit()  # якщо є записи (bookings), БД не дасть видалити, а хендлер поверне 409
    audit.log("user.delete", admin, "user", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
