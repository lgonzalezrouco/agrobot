from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^\x00]*$")]


class PatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_nulls(self) -> Self:
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("fields cannot be set to null")
        return self
