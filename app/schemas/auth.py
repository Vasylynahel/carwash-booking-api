from pydantic import BaseModel, EmailStr

from app.schemas.user import FullName, Password, Phone, UserRead


class RegisterRequest(BaseModel):
    # Ролі тут немає навмисно: самореєстрація завжди створює клієнта
    email: EmailStr
    password: Password
    full_name: FullName
    phone: Phone | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # секунд до завершення access-токена


class AuthResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class OAuthTokenResponse(BaseModel):
    """Формат, якого очікує кнопка Authorize у Swagger."""

    access_token: str
    token_type: str = "bearer"
