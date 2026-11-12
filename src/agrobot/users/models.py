from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from agrobot.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(200))
    # E.164 allows at most 15 digits plus the leading "+".
    phone_number: Mapped[str] = mapped_column(String(16), unique=True)
