import asyncio
import hashlib
from collections.abc import Sequence
from datetime import date
from typing import NamedTuple, Protocol

from agrobot.locations.models import Location
from agrobot.weather import WeatherEventType


class ProviderForecast(NamedTuple):
    weather_event_type: WeatherEventType
    day: date
    probability: int


class WeatherProvider(Protocol):
    async def get_forecasts(
        self, location: Location, days: Sequence[date]
    ) -> list[ProviderForecast]: ...


class FakeWeatherProvider:
    async def get_forecasts(
        self, location: Location, days: Sequence[date]
    ) -> list[ProviderForecast]:
        await asyncio.sleep(0.01)
        return [
            ProviderForecast(
                weather_event_type,
                day,
                _probability(location, day, weather_event_type),
            )
            for weather_event_type in WeatherEventType
            for day in days
        ]


def _probability(location: Location, day: date, weather_event_type: WeatherEventType) -> int:
    seed = f"{location.latitude}|{location.longitude}|{day}|{weather_event_type}"
    return int.from_bytes(hashlib.sha256(seed.encode()).digest()[:4]) % 101
