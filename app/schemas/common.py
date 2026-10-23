from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Формат пагінованої відповіді (такий самий чекатиме React-клієнт)."""

    items: list[T]
    total: int
    page: int
    limit: int
    pages: int
