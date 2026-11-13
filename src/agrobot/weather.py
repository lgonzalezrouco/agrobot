import enum

from sqlalchemy import Enum

from agrobot.core.db import pg_enum


class WeatherEventType(enum.StrEnum):
    FROST = "frost"
    RAIN = "rain"
    HAIL = "hail"
    HEAT_WAVE = "heat_wave"
    STRONG_WIND = "strong_wind"


def weather_event_type_column_type() -> Enum:
    return pg_enum(WeatherEventType, "weather_event_type")
