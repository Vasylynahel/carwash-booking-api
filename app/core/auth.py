from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.deps import DbSession
from app.models import User, UserRole

# auto_error=False: помилку відсутнього токена формуємо самі, у нашому єдиному форматі.
# tokenUrl потрібен, щоб у Swagger з'явилась кнопка Authorize
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


def get_current_user(db: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    """Автентифікація: дістає користувача з access-токена."""
    if not token:
        raise UnauthorizedError()
    payload = decode_token(token, "access")
    user = db.get(User, int(payload["sub"]))
    # Роль беремо з БД, а не з токена: якщо адмін змінив роль чи заблокував
    # користувача, це діє одразу, не чекаючи завершення токена
    if user is None or not user.is_active:
        raise UnauthorizedError("Обліковий запис недоступний")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Авторизація: пускає лише користувачів із переліченими ролями."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError("Недостатньо прав для виконання цієї операції")
        return user

    return checker


AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]
StaffUser = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.MASTER))]
