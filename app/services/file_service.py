import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import BusinessRuleError, PayloadTooLargeError

# Дозволені типи: розширення → MIME-тип, який має заявити клієнт
ALLOWED: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def _magic_matches(ext: str, head: bytes) -> bool:
    """Перевірка «магічних байтів»: ім'я й MIME-тип від клієнта легко підробити, а початок файлу — важче."""
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".pdf":
        return head.startswith(b"%PDF-")
    return False


def save_upload(upload: UploadFile) -> tuple[str, str, int]:
    """Перевіряє й зберігає файл. Повертає (ім'я на диску, MIME-тип, розмір)."""
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise BusinessRuleError(f"Непідтримуваний тип файлу. Дозволено: {', '.join(sorted(ALLOWED))}")
    if upload.content_type != ALLOWED[ext]:
        raise BusinessRuleError("MIME-тип файлу не збігається з його розширенням")

    head = upload.file.read(16)
    upload.file.seek(0)
    if not _magic_matches(ext, head):
        raise BusinessRuleError("Вміст файлу не відповідає заявленому типу")

    settings.upload_path.mkdir(parents=True, exist_ok=True)
    # Ім'я на диску генерую сама: оригінальне ім'я від клієнта не потрапляє в шлях
    # (захист від імен на кшталт ../../etc/passwd)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = settings.upload_path / stored_name

    size = 0
    try:
        with path.open("wb") as out:
            while chunk := upload.file.read(64 * 1024):
                size += len(chunk)
                if size > settings.max_file_size:
                    raise PayloadTooLargeError(
                        f"Файл завеликий: максимум {settings.max_file_size // (1024 * 1024)} МБ"
                    )
                out.write(chunk)
        if size == 0:
            raise BusinessRuleError("Файл порожній")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return stored_name, ALLOWED[ext], size


def delete_from_disk(stored_name: str) -> None:
    (settings.upload_path / stored_name).unlink(missing_ok=True)


def disk_path(stored_name: str) -> Path:
    return settings.upload_path / stored_name
