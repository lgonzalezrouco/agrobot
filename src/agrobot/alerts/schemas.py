import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic import Field as PydanticField

from agrobot.alerts.models import WeatherEventType

Threshold = Annotated[int, PydanticField(strict=True, ge=0, le=100)]


class AlertCreate(BaseModel):
    weather_event_type: WeatherEventType
    threshold: Threshold
    active: bool = True


class AlertUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: Threshold | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def reject_nulls(self) -> Self:
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("fields cannot be set to null")
        return self


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_id: uuid.UUID
    weather_event_type: WeatherEventType
    threshold: int
    active: bool
    created_at: datetime
    updated_at: datetime
