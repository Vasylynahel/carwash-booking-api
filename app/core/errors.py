from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Базова помилка бізнес-логіки. Хендлер нижче перетворює її на JSON."""

    status_code = 400

    def __init__(self, message: str, headers: dict[str, str] | None = None):
        self.message = message
        self.headers = headers


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class BusinessRuleError(AppError):
    status_code = 422


class UnauthorizedError(AppError):
    """401: не вхід — немає токена, він недійсний або прострочений."""

    status_code = 401

    def __init__(self, message: str = "Необхідна автентифікація"):
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    """403: користувача впізнали, але прав на цю дію в нього немає."""

    status_code = 403


class PayloadTooLargeError(AppError):
    status_code = 413


class TooManyRequestsError(AppError):
    status_code = 429


def _body(message: str, details: list | None = None) -> dict:
    body: dict = {"error": message}
    if details:
        body["details"] = details
    return body


def register_error_handlers(app: FastAPI) -> None:
    # Усі помилки віддаємо в одному форматі {"error": "...", "details": [...]},
    # щоб клієнту (React) було просто їх показувати.
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code, content=_body(exc.message), headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or e["loc"][0], "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_body("Помилка валідації даних", details))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=_body(str(exc.detail)))

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError):
        # Запасний варіант: основні конфлікти ловимо раніше з нормальним текстом,
        # а це страховка від порушення унікальності чи зовнішнього ключа в БД.
        return JSONResponse(
            status_code=409,
            content=_body("Операція порушує цілісність даних (дублікат або пов'язані записи)"),
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        # Деталі наружу не віддаємо, щоб не світити внутрішню будову сервера
        return JSONResponse(status_code=500, content=_body("Внутрішня помилка сервера"))
