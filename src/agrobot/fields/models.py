import uuid

from sqlalchemy import CheckConstraint, Double, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin
from agrobot.locations.models import Location


class Field(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fields"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)

    location: Mapped[Location] = relationship(lazy="joined")
