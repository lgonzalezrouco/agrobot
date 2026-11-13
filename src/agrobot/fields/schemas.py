import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField

from agrobot.core.schemas import Name, PatchModel

Latitude = Annotated[float, PydanticField(ge=-90, le=90)]
Longitude = Annotated[float, PydanticField(ge=-180, le=180)]


class FieldCreate(BaseModel):
    name: Name
    latitude: Latitude
    longitude: Longitude


class FieldUpdate(PatchModel):
    name: Name | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    latitude: float
    longitude: float


class FieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    latitude: float
    longitude: float
    location: LocationRead
    created_at: datetime
    updated_at: datetime
