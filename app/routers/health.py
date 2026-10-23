from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.deps import DbSession

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Перевірка стану сервера та бази даних")
def health(db: DbSession):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})
    return {"status": "ok", "database": "ok"}
