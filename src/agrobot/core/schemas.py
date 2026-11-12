from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class PatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def reject_nulls(self) -> Self:
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("fields cannot be set to null")
        return self
