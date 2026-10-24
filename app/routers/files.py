from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.audit import Audit
from app.core.auth import CurrentUser
from app.core.config import settings
from app.core.errors import BusinessRuleError, ForbiddenError, NotFoundError
from app.core.pagination import paginate
from app.deps import DbSession, Pager
from app.models import Car, StoredFile, User, UserRole
from app.schemas.common import Page
from app.schemas.file import FileRead
from app.services import file_service

router = APIRouter(prefix="/files", tags=["Файли"])


def _is_staff(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.MASTER)


def _get_accessible(db, file_id: int, user: User) -> StoredFile:
    stored = db.get(StoredFile, file_id)
    if stored is None:
        raise NotFoundError("Файл не знайдено")
    if stored.uploaded_by != user.id and not _is_staff(user):
        raise ForbiddenError("Немає доступу до цього файлу")
    return stored


def _check_car(db, car_id: int | None, user: User) -> None:
    if car_id is None:
        return
    car = db.get(Car, car_id)
    if car is None:
        raise NotFoundError("Автомобіль не знайдено")
    if car.owner_id != user.id and not _is_staff(user):
        raise ForbiddenError("Це не ваш автомобіль")


def _store(db, upload: UploadFile, user: User, car_id: int | None) -> StoredFile:
    name, mimetype, size = file_service.save_upload(upload)
    stored = StoredFile(
        filename=name,
        original_name=(upload.filename or name)[:255],
        mimetype=mimetype,
        size=size,
        uploaded_by=user.id,
        car_id=car_id,
    )
    db.add(stored)
    return stored


@router.post("/upload", response_model=FileRead, status_code=status.HTTP_201_CREATED, summary="Завантажити файл")
def upload_file(
    file: Annotated[UploadFile, File()],
    user: CurrentUser,
    db: DbSession,
    audit: Audit,
    car_id: Annotated[int | None, Form()] = None,
):
    _check_car(db, car_id, user)
    stored = _store(db, file, user, car_id)
    try:
        db.commit()
    except Exception:
        # Запис у БД не вдався: не залишаємо «осиротілий» файл на диску
        file_service.delete_from_disk(stored.filename)
        raise
    audit.log("file.upload", user, "file", stored.id)
    return stored


@router.post(
    "/upload-multiple",
    response_model=list[FileRead],
    status_code=status.HTTP_201_CREATED,
    summary="Завантажити кілька файлів одразу",
)
def upload_multiple(
    files: Annotated[list[UploadFile], File()],
    user: CurrentUser,
    db: DbSession,
    audit: Audit,
    car_id: Annotated[int | None, Form()] = None,
):
    if len(files) > settings.max_files_per_request:
        raise BusinessRuleError(f"За раз можна завантажити не більше {settings.max_files_per_request} файлів")
    _check_car(db, car_id, user)

    saved: list[StoredFile] = []
    try:
        for upload in files:
            saved.append(_store(db, upload, user, car_id))
        db.commit()
    except Exception:
        # Усе або нічого: якщо один файл невалідний, прибираємо й попередні
        db.rollback()
        for s in saved:
            file_service.delete_from_disk(s.filename)
        raise
    audit.log("file.upload_multiple", user, "file", None, {"ids": [s.id for s in saved]})
    return saved


@router.get("", response_model=Page[FileRead], summary="Список файлів")
def list_files(user: CurrentUser, db: DbSession, pager: Pager, car_id: int | None = None):
    stmt = select(StoredFile).order_by(StoredFile.id.desc())
    if not _is_staff(user):
        stmt = stmt.where(StoredFile.uploaded_by == user.id)
    if car_id is not None:
        stmt = stmt.where(StoredFile.car_id == car_id)
    return paginate(db, stmt, pager)


@router.get("/{file_id}", response_model=FileRead)
def get_file_info(file_id: int, user: CurrentUser, db: DbSession):
    return _get_accessible(db, file_id, user)


@router.get("/{file_id}/content", summary="Отримати вміст файлу")
def download_file(file_id: int, user: CurrentUser, db: DbSession):
    stored = _get_accessible(db, file_id, user)
    path = file_service.disk_path(stored.filename)
    if not path.exists():
        raise NotFoundError("Файл відсутній на диску")
    return FileResponse(path, media_type=stored.mimetype, filename=stored.original_name)


@router.put("/{file_id}", response_model=FileRead, summary="Замінити вміст файлу")
def replace_file(
    file_id: int, file: Annotated[UploadFile, File()], user: CurrentUser, db: DbSession, audit: Audit
):
    stored = _get_accessible(db, file_id, user)
    old_name = stored.filename
    name, mimetype, size = file_service.save_upload(file)
    stored.filename, stored.mimetype, stored.size = name, mimetype, size
    stored.original_name = (file.filename or name)[:255]
    try:
        db.commit()
    except Exception:
        file_service.delete_from_disk(name)
        raise
    file_service.delete_from_disk(old_name)  # старий файл видаляю лише після успішного збереження нового
    audit.log("file.replace", user, "file", stored.id)
    return stored


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, user: CurrentUser, db: DbSession, audit: Audit):
    stored = _get_accessible(db, file_id, user)
    name = stored.filename
    db.delete(stored)
    db.commit()
    file_service.delete_from_disk(name)
    audit.log("file.delete", user, "file", file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
