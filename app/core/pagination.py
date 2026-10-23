from math import ceil

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.deps import Pagination


def paginate(db: Session, stmt: Select, pager: Pagination) -> dict:
    """Рахує total по тому самому запиту (з фільтрами) і віддає одну сторінку."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(pager.limit).offset(pager.offset)).all()
    return {
        "items": items,
        "total": total,
        "page": pager.page,
        "limit": pager.limit,
        "pages": ceil(total / pager.limit),
    }
