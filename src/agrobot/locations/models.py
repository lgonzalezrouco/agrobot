from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("latitude", "longitude"),)

    latitude: Mapped[Decimal] = mapped_column(Numeric(4, 1))
    longitude: Mapped[Decimal] = mapped_column(Numeric(4, 1))
