import uuid

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from agrobot.weather import WeatherEventType, weather_event_type_column_type


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("field_id", "weather_event_type"),
        CheckConstraint("threshold BETWEEN 0 AND 100", name="threshold_range"),
    )

    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    weather_event_type: Mapped[WeatherEventType] = mapped_column(weather_event_type_column_type())
    threshold: Mapped[int]
    active: Mapped[bool] = mapped_column(default=True)
