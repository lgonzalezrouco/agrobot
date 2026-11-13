from collections.abc import Sequence
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


class PermanentDeliveryError(Exception):
    pass


class NotificationSender(Protocol):
    async def send(self, phone_number: str, contents: Sequence[NotificationContent]) -> None: ...


class FakeNotificationSender:
    async def send(self, phone_number: str, contents: Sequence[NotificationContent]) -> None:
        if phone_number.endswith("0000"):
            raise PermanentDeliveryError("phone number rejected")
        logger.info("notifications.fake_sent", notifications=[c._asdict() for c in contents])
