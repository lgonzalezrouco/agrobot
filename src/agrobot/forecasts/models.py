import uuid
from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from agrobot.weather import WeatherEventType, weather_event_type_column_type


class Forecast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("location_id", "weather_event_type", "day"),
        CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"))
    weather_event_type: Mapped[WeatherEventType] = mapped_column(weather_event_type_column_type())
    day: Mapped[date]
    probability: Mapped[int]
