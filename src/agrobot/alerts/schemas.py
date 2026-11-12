import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField

from agrobot.core.schemas import PatchModel
from agrobot.weather import WeatherEventType

Threshold = Annotated[int, PydanticField(strict=True, ge=0, le=100)]


class AlertCreate(BaseModel):
    weather_event_type: WeatherEventType
    threshold: Threshold
    active: bool = True


class AlertUpdate(PatchModel):
    threshold: Threshold | None = None
    active: bool | None = None


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_id: uuid.UUID
    weather_event_type: WeatherEventType
    threshold: int
    active: bool
    created_at: datetime
    updated_at: datetime
