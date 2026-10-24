from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.core.audit import Audit
from app.core.auth import CurrentUser
from app.core.errors import BusinessRuleError, ConflictError, UnauthorizedError
from app.core.rate_limit import auth_limit
from app.core.security import hash_password, verify_password
from app.deps import DbSession
from app.models import User, UserRole
from app.schemas.auth import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    OAuthTokenResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
)
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Автентифікація"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_limit)],
    summary="Реєстрація клієнта",
)
def register(data: RegisterRequest, db: DbSession, audit: Audit):
    email = data.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("Користувач з таким email уже існує")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        phone=data.phone,
        role=UserRole.CLIENT,
    )
    db.add(user)
    db.commit()
    audit.log("auth.register", user, "user", user.id)
    return AuthResponse(user=user, tokens=auth_service.issue_tokens(db, user))


@router.post(
    "/login",
    response_model=AuthResponse,
    dependencies=[Depends(auth_limit)],
    summary="Вхід за email і паролем",
)
def login(data: LoginRequest, db: DbSession, audit: Audit):
    user = auth_service.authenticate(db, data.email, data.password)
    if user is None:
        audit.log("auth.login_failed", None, details={"email": data.email.lower()})
        # Однакове повідомлення для хибного email і хибного пароля
        raise UnauthorizedError("Невірний email або пароль")
    audit.log("auth.login", user, "user", user.id)
    return AuthResponse(user=user, tokens=auth_service.issue_tokens(db, user))


@router.post(
    "/token",
    response_model=OAuthTokenResponse,
    dependencies=[Depends(auth_limit)],
    summary="Вхід для Swagger (форма): кнопка Authorize",
)
def login_form(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: DbSession, audit: Audit):
    # Окремий ендпоїнт лише для кнопки Authorize у Swagger: вона шле дані формою, а не JSON.
    # Поле username тут містить email.
    user = auth_service.authenticate(db, form.username, form.password)
    if user is None:
        audit.log("auth.login_failed", None, details={"email": form.username.lower()})
        raise UnauthorizedError("Невірний email або пароль")
    audit.log("auth.login", user, "user", user.id)
    return OAuthTokenResponse(access_token=auth_service.issue_tokens(db, user).access_token)


@router.post(
    "/refresh",
    response_model=TokenPair,
    dependencies=[Depends(auth_limit)],
    summary="Оновлення пари токенів (ротація refresh-токена)",
)
def refresh(data: RefreshRequest, db: DbSession):
    _, tokens = auth_service.rotate_refresh_token(db, data.refresh_token)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Вихід: відкликання refresh-токена")
def logout(data: LogoutRequest, db: DbSession, audit: Audit):
    if data.refresh_token:
        user_id = auth_service.revoke_token(db, data.refresh_token)
        if user_id:
            audit.log("auth.logout", user_id, "user", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserRead, summary="Поточний користувач")
def me(user: CurrentUser):
    return user


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Зміна пароля (усі сесії завершуються)",
)
def change_password(data: ChangePasswordRequest, user: CurrentUser, db: DbSession, audit: Audit):
    if not verify_password(data.current_password, user.password_hash):
        # 422, а не 401: клієнтський перехоплювач на 401 розлогінює користувача, а сесія тут чинна
        raise BusinessRuleError("Поточний пароль невірний")
    if data.current_password == data.new_password:
        raise BusinessRuleError("Новий пароль має відрізнятися від поточного")
    user.password_hash = hash_password(data.new_password)
    db.commit()
    # Після зміни пароля старі refresh-токени мають перестати працювати на всіх пристроях
    auth_service.revoke_all(db, user.id)
    audit.log("auth.change_password", user, "user", user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
