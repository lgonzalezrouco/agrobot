from datetime import date
from typing import NamedTuple, Protocol

import structlog

from agrobot.weather import WeatherEventType

logger = structlog.get_logger(__name__)


class NotificationContent(NamedTuple):
    field_name: str
    weather_event_type: WeatherEventType
    day: date
    probability: int
    threshold: int


class NotificationSender(Protocol):
    async def send(self, phone_number: str, content: NotificationContent) -> None: ...


class FakeNotificationSender:
    async def send(self, phone_number: str, content: NotificationContent) -> None:
        logger.info("notifications.fake_sent", **content._asdict())
