from datetime import date
from typing import NamedTuple, Protocol

import structlog

from agrobot.weather import WeatherEventType

logger = structlog.get_logger(__name__)


class NotificationMessage(NamedTuple):
    field_name: str
    weather_event_type: WeatherEventType
    day: date
    probability: int
    threshold: int


class NotificationSender(Protocol):
    async def send(self, phone_number: str, message: NotificationMessage) -> None: ...


class FakeNotificationSender:
    async def send(self, phone_number: str, message: NotificationMessage) -> None:
        logger.info("notifications.fake_sent", **message._asdict())
