from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from agrobot.notifications.models import NotificationStatus


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    day: date
    probability: int
    threshold: int
    status: NotificationStatus
    attempts: int
    sent_at: datetime | None
