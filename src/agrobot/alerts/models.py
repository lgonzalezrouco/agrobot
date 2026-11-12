import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from agrobot.weather import WeatherEventType


def _values(members: type[StrEnum]) -> list[str]:
    return [member.value for member in members]


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("field_id", "weather_event_type"),
        CheckConstraint("threshold BETWEEN 0 AND 100", name="threshold_range"),
    )

    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    weather_event_type: Mapped[WeatherEventType] = mapped_column(
        Enum(
            WeatherEventType,
            name="weather_event_type",
            values_callable=_values,
        )
    )
    threshold: Mapped[int]
    active: Mapped[bool] = mapped_column(default=True)
