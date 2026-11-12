"""Import every feature's models here so Alembic autogenerate sees them."""

from agrobot.core.db import Base
from agrobot.users.models import User

__all__ = ["Base", "User"]
