from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_name: str
    mimetype: str
    size: int
    uploaded_by: int
    car_id: int | None
    created_at: datetime
