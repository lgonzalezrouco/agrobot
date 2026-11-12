import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

E164PhoneNumber = Annotated[str, Field(pattern=r"^\+[1-9]\d{1,14}$")]


class UserCreate(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    phone_number: E164PhoneNumber


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    phone_number: str
    created_at: datetime
    updated_at: datetime
