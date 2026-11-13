"""Import every feature's models here so Alembic autogenerate sees them."""

from agrobot.alerts.models import Alert
from agrobot.core.db import Base
from agrobot.fields.models import Field
from agrobot.forecasts.models import Forecast
from agrobot.locations.models import Location
from agrobot.notifications.models import Notification
from agrobot.users.models import User
from agrobot.worker.models import JobRun

__all__ = ["Alert", "Base", "Field", "Forecast", "JobRun", "Location", "Notification", "User"]
