"""Import every feature's models here so Alembic autogenerate sees them."""

from agrobot.alerts.models import Alert
from agrobot.core.db import Base
from agrobot.fields.models import Field
from agrobot.forecasts.models import Forecast
from agrobot.locations.models import Location
from agrobot.notifications.models import Notification
from agrobot.users.models import User

__all__ = ["Alert", "Base", "Field", "Forecast", "Location", "Notification", "User"]
