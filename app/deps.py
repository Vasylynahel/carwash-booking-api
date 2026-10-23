from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db

DbSession = Annotated[Session, Depends(get_db)]


class Pagination:
    """Параметри ?page=1&limit=10. Верхню межу limit ставлю, щоб не просили 10 000 рядків."""

    def __init__(
        self,
        page: Annotated[int, Query(ge=1)] = 1,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ):
        self.page = page
        self.limit = limit

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


Pager = Annotated[Pagination, Depends()]
